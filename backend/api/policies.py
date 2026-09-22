"""Кто пришёл и что ему можно: политики доступа для маршрутов.

Каждый маршрут под /api/ обязан объявить ровно одну политику — verify_policies
проверяет это при старте, чтобы забытая зависимость не открыла дверь молча.
"""

import secrets
import time

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from ..service.accounts import session_hash, user_metadata
from ..core.secrets import digest
from ..db.domain.models import APIKey, AdminSession, IntegrationClient, SavedPipeline, User

bearer = HTTPBearer(auto_error=False, scheme_name="API key", description="Integration API key")
COOKIE = "ocr_admin_session"
SESSION_SECONDS = 12 * 60 * 60


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


def workspace_only(request: Request, _identity: None = Depends(authenticate)):
    if not request.state.user_id:
        raise HTTPException(403, "Требуется вход пользователя")


def require_permission(request, permission):
    if not request.state.user_id and permission not in request.state.permissions:
        raise HTTPException(403, "Ключу не разрешено это действие")


def client_visible(query, model, request):
    """Apply ownership and current pipeline access to both results and jobs."""
    if request.state.user_id:
        return query
    allowed = select(SavedPipeline.id).where(SavedPipeline.id.in_(request.state.pipeline_ids), SavedPipeline.deleted == 0)
    return query.where(model.client_id == request.state.client_id, model.client_id.is_not(None), model.pipeline_id.in_(allowed))


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
