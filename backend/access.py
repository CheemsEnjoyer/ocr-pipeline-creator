import hashlib
import logging
import math
import os
import re
import secrets
import time
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, select

from .database import APIKey, AdminSession, SavedPipeline
from .models import User, IntegrationClient
from .accounts import initialize_account, session_hash, user_metadata, verify_password
from .throttle import FAILED_LOGIN_WINDOW, MAX_FAILED_LOGINS, LoginThrottle

bearer = HTTPBearer(auto_error=False, scheme_name="API key", description="Integration API key")
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
    request.state.client_id = None
    request.state.permissions = []
    request.state.user_id = None
    if request.headers.get("authorization") is not None:
        # В заголовке принимаются только ключи интеграций; администратор входит через сессию.
        if credentials is None or len(credentials.credentials) > 512:
            raise HTTPException(401, "Некорректный API-ключ")
        with request.app.state.sessions() as session:
            key = session.scalar(select(APIKey).where(APIKey.token_hash == digest(credentials.credentials), APIKey.revoked_at.is_(None)))
            if key is None:
                raise HTTPException(401, "API-ключ недействителен или отозван")
            client = session.get(IntegrationClient, key.client_id)
            if client is None:
                raise HTTPException(401, "Клиент ключа не найден")
            request.state.client_id = client.id
            request.state.permissions = list(key.permissions)
            request.state.pipeline_ids = list(client.pipeline_ids)
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


def require_permission(request, permission):
    if not request.state.user_id and permission not in request.state.permissions:
        raise HTTPException(403, "Ключу не разрешено это действие")


def client_visible(query, model, request):
    """Apply ownership and current pipeline access to both results and jobs."""
    if request.state.user_id:
        return query
    allowed = select(SavedPipeline.id).where(SavedPipeline.id.in_(request.state.pipeline_ids), SavedPipeline.deleted == 0)
    return query.where(model.client_id == request.state.client_id, model.client_id.is_not(None), model.pipeline_id.in_(allowed))


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


class ClientSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    pipeline_ids: list[str] = Field(max_length=1000)


class KeySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    client_id: str = Field(min_length=1, max_length=36)
    permissions: list[Literal["run", "results", "history"]] = Field(max_length=3)


def metadata(key, client):
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "client_id": key.client_id,
            "client_name": client.name, "permissions": key.permissions, "pipeline_ids": client.pipeline_ids,
            "created_at": key.created_at, "revoked_at": key.revoked_at}


def client_metadata(client):
    return {"id": client.id, "name": client.name, "pipeline_ids": client.pipeline_ids, "created_at": client.created_at}


def validate_settings(session, payload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название клиента")
    ids = list(dict.fromkeys(payload.pipeline_ids))
    available = set(session.scalars(select(SavedPipeline.id).where(SavedPipeline.id.in_(ids), SavedPipeline.deleted == 0)))
    if set(ids) != available:
        raise HTTPException(422, "Один из выбранных пайплайнов удалён или не существует")
    return name, ids


@router.post("/api/auth/login", tags=["Authentication"], dependencies=[Depends(public)])
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


@router.get("/api/auth/session", tags=["Authentication"], dependencies=[Depends(workspace_only)])
def current_session(request: Request):
    return request.state.user


@router.post("/api/auth/logout", tags=["Authentication"], dependencies=[Depends(workspace_only)])
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


@router.get("/api/keys", tags=["API Keys"], dependencies=[Depends(admin_only)])
def list_keys(request: Request):
    with request.app.state.sessions() as session:
        rows = session.execute(select(APIKey, IntegrationClient).join(IntegrationClient).order_by(APIKey.created_at.desc(), APIKey.id))
        return {"keys": [metadata(key, client) for key, client in rows]}


@router.get("/api/clients", tags=["API Clients"], dependencies=[Depends(admin_only)])
def list_clients(request: Request):
    with request.app.state.sessions() as session:
        return {"clients": [client_metadata(row) for row in session.scalars(select(IntegrationClient).order_by(IntegrationClient.created_at.desc(), IntegrationClient.id))]}


@router.post("/api/clients", status_code=201, tags=["API Clients"], dependencies=[Depends(admin_only)])
def create_client(payload: ClientSettings, request: Request):
    from .repositories import now
    with request.app.state.sessions.begin() as session:
        name, ids = validate_settings(session, payload)
        client = IntegrationClient(id=str(uuid4()), name=name, pipeline_ids=ids, created_at=now())
        session.add(client)
        return {"client": client_metadata(client)}


@router.patch("/api/clients/{client_id}", tags=["API Clients"], dependencies=[Depends(admin_only)])
def update_client(client_id: str, payload: ClientSettings, request: Request):
    with request.app.state.sessions.begin() as session:
        client = session.get(IntegrationClient, client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        client.name, client.pipeline_ids = validate_settings(session, payload)
        return {"client": client_metadata(client)}


def key_settings(session, payload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название ключа")
    client = session.get(IntegrationClient, payload.client_id)
    if client is None:
        raise HTTPException(422, "Выберите существующего клиента")
    return name, client, list(dict.fromkeys(payload.permissions))


@router.post("/api/keys", status_code=201, tags=["API Keys"], dependencies=[Depends(admin_only)])
def create_key(payload: KeySettings, request: Request):
    from datetime import datetime, timezone
    token = "ocr_" + secrets.token_urlsafe(32)
    with request.app.state.sessions() as session:
        name, client, permissions = key_settings(session, payload)
        key = APIKey(id=str(uuid4()), name=name, token_hash=digest(token), prefix=token[:12], client_id=client.id, permissions=permissions, created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        session.add(key)
        session.commit()
        return {"key": metadata(key, client), "token": token}


@router.patch("/api/keys/{key_id}", tags=["API Keys"], dependencies=[Depends(admin_only)])
def update_key(key_id: str, payload: KeySettings, request: Request):
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None or key.revoked_at:
            raise HTTPException(404, "Активный ключ не найден")
        if payload.client_id != key.client_id:
            raise HTTPException(409, "Владельца ключа менять нельзя. Создайте новый ключ для другого клиента.")
        key.name, client, key.permissions = key_settings(session, payload)
        session.commit()
        return {"key": metadata(key, client)}


@router.delete("/api/keys/{key_id}", tags=["API Keys"], dependencies=[Depends(admin_only)])
def revoke_key(key_id: str, request: Request):
    from datetime import datetime, timezone
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None:
            raise HTTPException(404, "Ключ не найден")
        key.revoked_at = key.revoked_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        session.commit()
    return {"status": "ok"}
