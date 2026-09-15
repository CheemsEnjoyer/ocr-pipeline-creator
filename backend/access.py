import hashlib
import logging
import math
import os
import re
import secrets
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .database import APIKey, AdminSession, SavedPipeline
from .models import User
from .accounts import initialize_account, session_hash, user_metadata, verify_password
from .throttle import FAILED_LOGIN_WINDOW, MAX_FAILED_LOGINS, LoginThrottle

bearer = HTTPBearer(auto_error=False, scheme_name="API key", description="Ключ интеграции")
COOKIE = "ocr_admin_session"
SESSION_SECONDS = 12 * 60 * 60
PASSWORD_FILE = "admin-password.txt"
MIN_PASSWORD_LENGTH = 8
# Пароль, в отличие от ключа, бывает коротким, поэтому перебор ограничен.
router = APIRouter()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(login, password):
    # Медленный хэш: по отпечатку в таблице сессий пароль быстро не подобрать.
    return hashlib.scrypt(f"{login}\0{password}".encode("utf-8"), salt=b"ocr-flow-admin", n=2**14, r=8, p=1, dklen=32).hex()


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
    app.state.login_throttle = LoginThrottle(app.state.sessions)
    initialize_account(app, login, app.state.admin_fingerprint)


def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer)):
    """Определяет, кто пришёл: администратор по сессии или ключ интеграции по заголовку.

    Права здесь не проверяются: за них отвечают public, admin_only и integration_allowed,
    объявленные рядом с самими маршрутами.
    """
    request.state.is_admin = False
    request.state.pipeline_ids = []
    request.state.api_key_id = None
    request.state.user_id = None
    if request.headers.get("authorization") is not None:
        # В заголовке принимаются только ключи интеграций; администратор входит через сессию.
        if credentials is None or len(credentials.credentials) > 512:
            raise HTTPException(401, "Некорректный API-ключ")
        with request.app.state.sessions() as session:
            key = session.scalar(select(APIKey).where(APIKey.token_hash == digest(credentials.credentials), APIKey.revoked_at.is_(None)))
            if key is None:
                raise HTTPException(401, "API-ключ недействителен или отозван")
            request.state.pipeline_ids = list(key.pipeline_ids)
            request.state.api_key_id = key.id
        return
    cookie = request.cookies.get(COOKIE)
    if request.app.state.auth_provider == "keycloak":
        if not cookie or len(cookie) > 512:
            raise HTTPException(401, "Требуется вход через Keycloak")
        user = request.app.state.keycloak.authenticate(cookie)
        request.state.user = user
        request.state.user_id = user["id"]
        request.state.is_admin = user["role"] == "admin"
        return
    if cookie and len(cookie) <= 512:
        with request.app.state.sessions() as session:
            row = session.get(AdminSession, digest(cookie))
            # admin_hash хранит отпечаток логина и пароля: их смена завершает все сессии.
            if row and row.expires_at > int(time.time()):
                user = session.get(User, row.user_id or request.app.state.bootstrap_user_id)
                if user and user.status == "active" and secrets.compare_digest(row.admin_hash, session_hash(user)) and (not user.is_bootstrap or secrets.compare_digest(row.admin_hash, request.app.state.admin_fingerprint)):
                    request.state.is_admin = user.role == "admin"
                    request.state.user_id = user.id
                    request.state.user = user_metadata(user)
                    return
    raise HTTPException(401, "Требуется вход пользователя или API-ключ")


def public():
    """Маршрут работает без входа: состояние сервера и форма входа."""


def admin_only(request: Request, _identity: None = Depends(authenticate)):
    """Только интерфейс администратора: ключу интеграции такой маршрут закрыт."""
    if not request.state.is_admin:
        raise HTTPException(403, "Для этого действия нужны права администратора")


def integration_allowed(_identity: None = Depends(authenticate)):
    """Администратор и ключ интеграции. Свои пайплайны и документы ключу выбирают сами обработчики."""


def workspace_only(request: Request, _identity: None = Depends(authenticate)):
    if not request.state.user_id:
        raise HTTPException(403, "Требуется вход пользователя")


POLICIES = (public, admin_only, integration_allowed, workspace_only)


def verify_policies(app):
    """Маршрут без политики доступа — ошибка запуска, а не тихо открытая дверь."""
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or not hasattr(route, "dependant"):
            continue
        declared = {dependency.call for dependency in route.dependant.dependencies if dependency.call in POLICIES}
        if len(declared) != 1:
            raise RuntimeError(f"{path}: укажите ровно одну политику доступа — public, admin_only или integration_allowed")


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


@router.post("/api/auth/login", dependencies=[Depends(public)])
def login(payload: Login, request: Request, response: Response):
    if request.app.state.auth_provider == "keycloak":
        raise HTTPException(409, "Используйте вход через Keycloak")
    throttle = request.app.state.login_throttle
    identity = {}
    def check():
        with request.app.state.sessions() as session:
            user = session.scalar(select(User).where(User.login == payload.login.strip(), User.status == "active"))
            if user and (secrets.compare_digest(fingerprint(user.login, payload.password), request.app.state.admin_fingerprint) if user.is_bootstrap else verify_password(payload.password, user.password_hash)):
                identity.update(id=user.id, hash=session_hash(user))
                return True
            if user is None:
                fingerprint(payload.login.strip(), payload.password)
            return False
    accepted, retry = throttle.verify(check)
    if retry:
        raise HTTPException(429, f"Слишком много неудачных попыток входа. Повторите через {math.ceil(retry / 60)} мин.")
    if not accepted:
        raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_urlsafe(32)
    with request.app.state.sessions.begin() as session:
        user = session.scalar(select(User).where(User.id == identity["id"]).with_for_update())
        if user is None or user.status != "active" or not secrets.compare_digest(session_hash(user), identity["hash"]):
            raise HTTPException(401, "Учётная запись изменена. Войдите снова")
        session.execute(delete(AdminSession).where(AdminSession.expires_at <= int(time.time())))
        previous = request.cookies.get(COOKIE)
        if previous:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(previous)))
        session.add(AdminSession(token_hash=digest(token), admin_hash=identity["hash"], user_id=user.id, expires_at=int(time.time()) + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=os.getenv("OCR_SECURE_COOKIE") == "1", path="/")
    return {"status": "ok"}


@router.get("/api/auth/session", dependencies=[Depends(workspace_only)])
def current_session(request: Request):
    return request.state.user


@router.post("/api/auth/logout", dependencies=[Depends(workspace_only)])
def logout(request: Request, response: Response):
    if request.app.state.auth_provider == "keycloak":
        from .api.keycloak import end_session
        return end_session(request, response)
    token = request.cookies.get(COOKIE)
    if token:
        with request.app.state.sessions.begin() as session:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(token)))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=os.getenv("OCR_SECURE_COOKIE") == "1")
    return {"status": "ok"}


@router.get("/api/keys", dependencies=[Depends(admin_only)])
def list_keys(request: Request):
    with request.app.state.sessions() as session:
        return {"keys": [metadata(key) for key in session.scalars(select(APIKey).order_by(APIKey.created_at.desc(), APIKey.id))]}


@router.post("/api/keys", status_code=201, dependencies=[Depends(admin_only)])
def create_key(payload: KeySettings, request: Request):
    from datetime import datetime, timezone
    token = "ocr_" + secrets.token_urlsafe(32)
    with request.app.state.sessions() as session:
        name, ids = validate_settings(session, payload)
        key = APIKey(id=str(uuid4()), name=name, token_hash=digest(token), prefix=token[:12], pipeline_ids=ids, created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        session.add(key)
        session.commit()
        return {"key": metadata(key), "token": token}


@router.patch("/api/keys/{key_id}", dependencies=[Depends(admin_only)])
def update_key(key_id: str, payload: KeySettings, request: Request):
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None or key.revoked_at:
            raise HTTPException(404, "Активный ключ не найден")
        key.name, key.pipeline_ids = validate_settings(session, payload)
        session.commit()
        return {"key": metadata(key)}


@router.delete("/api/keys/{key_id}", dependencies=[Depends(admin_only)])
def revoke_key(key_id: str, request: Request):
    from datetime import datetime, timezone
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None:
            raise HTTPException(404, "Ключ не найден")
        key.revoked_at = key.revoked_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        session.commit()
    return {"status": "ok"}
