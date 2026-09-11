import hashlib
import logging
import math
import os
import re
import secrets
import threading
import time
from collections import deque
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .database import APIKey, AdminSession, SavedPipeline

bearer = HTTPBearer(auto_error=False, scheme_name="API key", description="Ключ интеграции")
COOKIE = "ocr_admin_session"
SESSION_SECONDS = 12 * 60 * 60
PASSWORD_FILE = "admin-password.txt"
MIN_PASSWORD_LENGTH = 8
# Пароль, в отличие от ключа, бывает коротким, поэтому перебор ограничен.
MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 10 * 60
router = APIRouter()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(login, password):
    # Медленный хэш: по отпечатку в таблице сессий пароль быстро не подобрать.
    return hashlib.scrypt(f"{login}\0{password}".encode("utf-8"), salt=b"ocr-flow-admin", n=2**14, r=8, p=1, dklen=32).hex()


class LoginThrottle:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = deque()

    def retry_after(self, moment):
        while self.failures and moment - self.failures[0] >= FAILED_LOGIN_WINDOW:
            self.failures.popleft()
        return FAILED_LOGIN_WINDOW - (moment - self.failures[0]) if len(self.failures) >= MAX_FAILED_LOGINS else 0


def initialize_admin(app, storage):
    login = os.getenv("OCR_ADMIN_LOGIN", "").strip() or "admin"
    password = os.getenv("OCR_ADMIN_PASSWORD", "")
    source = "OCR_ADMIN_PASSWORD"
    if not password:
        path = storage / PASSWORD_FILE
        source = f"Файл {path}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            password = path.read_text(encoding="utf-8").strip()
        else:
            password = secrets.token_urlsafe(18)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(password + chr(10))
        logging.getLogger("uvicorn.error").info("Вход администратора: логин %s, пароль хранится в %s", login, path)
    if len(login) > 120:
        raise RuntimeError("OCR_ADMIN_LOGIN: логин должен быть не длиннее 120 символов")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"{source}: пароль администратора должен содержать не менее {MIN_PASSWORD_LENGTH} символов")
    app.state.admin_fingerprint = fingerprint(login, password)
    app.state.login_throttle = LoginThrottle()


def require_access(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer)):
    path = request.url.path
    if path in ("/api/health", "/api/auth/login"):
        return
    request.state.is_admin = False
    request.state.pipeline_ids = []
    authorization = request.headers.get("authorization")
    if authorization is not None:
        # В заголовке принимаются только ключи интеграций; администратор входит через сессию.
        if credentials is None or len(credentials.credentials) > 512:
            raise HTTPException(401, "Некорректный API-ключ")
        with request.app.state.sessions() as session:
            key = session.scalar(select(APIKey).where(APIKey.token_hash == digest(credentials.credentials), APIKey.revoked_at.is_(None)))
            if key is None:
                raise HTTPException(401, "API-ключ недействителен или отозван")
            request.state.pipeline_ids = list(key.pipeline_ids)
        # Основной адрес интеграций — /api/v1; пути без версии разрешены для совместимости.
        allowed = (request.method == "GET" and path in ("/api/pipelines", "/api/v1/pipelines")) or (
            request.method == "POST" and (path in ("/api/pipeline/run", "/api/v1/pipeline/run") or re.fullmatch(r"/api(?:/v1)?/pipelines/[^/]+/run", path))
        )
        if not allowed:
            raise HTTPException(403, "Этот API-ключ разрешает только просмотр и запуск назначенных пайплайнов")
        return
    cookie = request.cookies.get(COOKIE)
    if cookie and len(cookie) <= 512:
        with request.app.state.sessions() as session:
            row = session.get(AdminSession, digest(cookie))
            # admin_hash хранит отпечаток логина и пароля: их смена завершает все сессии.
            if row and row.expires_at > int(time.time()) and secrets.compare_digest(row.admin_hash, request.app.state.admin_fingerprint):
                request.state.is_admin = True
                return
    raise HTTPException(401, "Требуется вход администратора или API-ключ")


class Login(BaseModel):
    login: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class KeySettings(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    pipeline_ids: list[str] = Field(min_length=1, max_length=1000)


def metadata(key):
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "pipeline_ids": key.pipeline_ids, "created_at": key.created_at, "revoked_at": key.revoked_at}


def validate_settings(session, payload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название ключа")
    ids = list(dict.fromkeys(payload.pipeline_ids))
    available = set(session.scalars(select(SavedPipeline.id).where(SavedPipeline.id.in_(ids), SavedPipeline.deleted == 0)))
    if set(ids) != available:
        raise HTTPException(422, "Один из выбранных пайплайнов удалён или не существует")
    return name, ids


@router.post("/api/auth/login")
def login(payload: Login, request: Request, response: Response):
    throttle = request.app.state.login_throttle
    # Проверки идут по одной: счётчик точен, а параллельные scrypt не съедают память.
    with throttle.lock:
        moment = time.monotonic()
        retry = throttle.retry_after(moment)
        if retry:
            raise HTTPException(429, f"Слишком много неудачных попыток входа. Повторите через {math.ceil(retry / 60)} мин.")
        if not secrets.compare_digest(fingerprint(payload.login.strip(), payload.password), request.app.state.admin_fingerprint):
            throttle.failures.append(moment)
            raise HTTPException(401, "Неверный логин или пароль")
        throttle.failures.clear()
    token = secrets.token_urlsafe(32)
    with request.app.state.sessions.begin() as session:
        session.execute(delete(AdminSession).where(AdminSession.expires_at <= int(time.time())))
        previous = request.cookies.get(COOKIE)
        if previous:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(previous)))
        session.add(AdminSession(token_hash=digest(token), admin_hash=request.app.state.admin_fingerprint, expires_at=int(time.time()) + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=os.getenv("OCR_SECURE_COOKIE") == "1", path="/")
    return {"status": "ok"}


@router.get("/api/auth/session")
def current_session():
    return {"role": "admin"}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with request.app.state.sessions.begin() as session:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(token)))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=os.getenv("OCR_SECURE_COOKIE") == "1")
    return {"status": "ok"}


@router.get("/api/keys")
def list_keys(request: Request):
    with request.app.state.sessions() as session:
        return {"keys": [metadata(key) for key in session.scalars(select(APIKey).order_by(APIKey.created_at.desc(), APIKey.id))]}


@router.post("/api/keys", status_code=201)
def create_key(payload: KeySettings, request: Request):
    from datetime import datetime, timezone
    token = "ocr_" + secrets.token_urlsafe(32)
    with request.app.state.sessions() as session:
        name, ids = validate_settings(session, payload)
        key = APIKey(id=str(uuid4()), name=name, token_hash=digest(token), prefix=token[:12], pipeline_ids=ids, created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        session.add(key)
        session.commit()
        return {"key": metadata(key), "token": token}


@router.patch("/api/keys/{key_id}")
def update_key(key_id: str, payload: KeySettings, request: Request):
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None or key.revoked_at:
            raise HTTPException(404, "Активный ключ не найден")
        key.name, key.pipeline_ids = validate_settings(session, payload)
        session.commit()
        return {"key": metadata(key)}


@router.delete("/api/keys/{key_id}")
def revoke_key(key_id: str, request: Request):
    from datetime import datetime, timezone
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None:
            raise HTTPException(404, "Ключ не найден")
        key.revoked_at = key.revoked_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        session.commit()
    return {"status": "ok"}
