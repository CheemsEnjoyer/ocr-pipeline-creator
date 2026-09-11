import hashlib
import logging
import os
import re
import secrets
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .database import APIKey, AdminSession, SavedPipeline

bearer = HTTPBearer(auto_error=False, scheme_name="API key", description="Ключ администратора или ключ интеграции")
COOKIE = "ocr_admin_session"
SESSION_SECONDS = 12 * 60 * 60
router = APIRouter()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def initialize_admin(storage):
    token = os.getenv("OCR_ADMIN_KEY", "").strip()
    if not token:
        path = storage / "admin-api-key.txt"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            token = path.read_text(encoding="utf-8").strip()
        else:
            token = "ocr_admin_" + secrets.token_urlsafe(32)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(token + chr(10))
        logging.getLogger("uvicorn.error").info("Ключ входа администратора хранится в %s", path)
    if len(token) < 32:
        # Короткий ключ может прийти и из повреждённого файла — называем реальный источник.
        source = "OCR_ADMIN_KEY" if os.getenv("OCR_ADMIN_KEY", "").strip() else f"Файл {storage / 'admin-api-key.txt'}"
        raise RuntimeError(f"{source}: ключ администратора должен содержать не менее 32 символов")
    return digest(token)


def require_access(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer)):
    path = request.url.path
    if path in ("/api/health", "/api/auth/login"):
        return
    request.state.is_admin = False
    request.state.pipeline_ids = []
    authorization = request.headers.get("authorization")
    if authorization is not None:
        if credentials is None or len(credentials.credentials) > 512:
            raise HTTPException(401, "Некорректный API-ключ")
        token_hash = digest(credentials.credentials)
        if secrets.compare_digest(token_hash, request.app.state.admin_hash):
            request.state.is_admin = True
            return
        with request.app.state.sessions() as session:
            key = session.scalar(select(APIKey).where(APIKey.token_hash == token_hash, APIKey.revoked_at.is_(None)))
            if key is None:
                raise HTTPException(401, "API-ключ недействителен или отозван")
            request.state.pipeline_ids = list(key.pipeline_ids)
        allowed = (request.method == "GET" and path == "/api/pipelines") or (
            request.method == "POST" and (path == "/api/pipeline/run" or re.fullmatch(r"/api/pipelines/[^/]+/run", path))
        )
        if not allowed:
            raise HTTPException(403, "Этот API-ключ разрешает только просмотр и запуск назначенных пайплайнов")
        return
    cookie = request.cookies.get(COOKIE)
    if cookie and len(cookie) <= 512:
        with request.app.state.sessions() as session:
            row = session.get(AdminSession, digest(cookie))
            if row and row.expires_at > int(time.time()) and secrets.compare_digest(row.admin_hash, request.app.state.admin_hash):
                request.state.is_admin = True
                return
    raise HTTPException(401, "Требуется вход администратора или API-ключ")


class Login(BaseModel):
    key: str = Field(min_length=1, max_length=512)


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
    if not secrets.compare_digest(digest(payload.key), request.app.state.admin_hash):
        raise HTTPException(401, "Неверный ключ администратора")
    token = secrets.token_urlsafe(32)
    with request.app.state.sessions.begin() as session:
        session.execute(delete(AdminSession).where(AdminSession.expires_at <= int(time.time())))
        previous = request.cookies.get(COOKIE)
        if previous:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(previous)))
        session.add(AdminSession(token_hash=digest(token), admin_hash=request.app.state.admin_hash, expires_at=int(time.time()) + SESSION_SECONDS))
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
