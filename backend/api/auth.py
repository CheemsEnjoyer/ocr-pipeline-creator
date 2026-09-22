"""Вход и выход локального администратора."""

import math
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from ..service.accounts import session_hash, verify_password
from ..core.secrets import digest, fingerprint
from ..db.domain.models import AdminSession, User
from ..schema.access import Login
from .policies import COOKIE, SESSION_SECONDS, public, workspace_only

router = APIRouter(tags=["Authentication"])


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
        from .keycloak import end_session
        return end_session(request, response)
    token = request.cookies.get(COOKIE)
    if token:
        with request.app.state.sessions.begin() as session:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == digest(token)))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=os.getenv("OCR_SECURE_COOKIE") == "1")
    return {"status": "ok"}
