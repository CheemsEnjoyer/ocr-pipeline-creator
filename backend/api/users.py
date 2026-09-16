import secrets
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ..access import admin_only, public, digest
from ..accounts import hash_password, user_metadata
from ..models import AdminSession, User, LoginGuard
from ..repositories import now


class Invite(BaseModel):
    login: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "user"] = "user"


class RoleUpdate(BaseModel):
    role: Literal["admin", "user"]


class AcceptInvite(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=8, max_length=512)


def create_router(app, storage):
    if app.state.auth_provider == "keycloak":
        from .keycloak_users import create_router as external_router
        return external_router(app, storage)
    router = APIRouter(tags=["Пользователи"])

    @router.get("/api/users", dependencies=[Depends(admin_only)])
    def list_users():
        with app.state.sessions() as session:
            return {"users": [user_metadata(user) for user in session.scalars(select(User).where(User.status != "deleted").order_by(User.created_at, User.id))]}

    @router.post("/api/users/invite", status_code=201, dependencies=[Depends(admin_only)])
    def invite(payload: Invite):
        login, name = payload.login.strip(), payload.name.strip()
        if not login or not name:
            raise HTTPException(422, "Укажите имя и логин")
        token = secrets.token_urlsafe(32)
        with app.state.sessions.begin() as session:
            session.scalar(select(LoginGuard).where(LoginGuard.id == "admin").with_for_update())
            user = session.scalar(select(User).where(User.login == login))
            if user and user.status != "deleted":
                raise HTTPException(409, "Этот логин уже занят")
            if user is None:
                user = User(id=str(uuid4()), login=login, name=name, role=payload.role, status="invited", is_bootstrap=0, created_at=now())
                session.add(user)
            user.name, user.role, user.status = name, payload.role, "invited"
            user.password_hash = None
            user.invite_hash, user.invite_expires = digest(token), time.time() + 72 * 3600
            session.flush()
            result = user_metadata(user)
        return {"user": result, "invitePath": f"/invite#token={token}", "expiresIn": 72 * 3600}

    @router.patch("/api/users/{user_id}", dependencies=[Depends(admin_only)])
    def update_role(user_id: str, payload: RoleUpdate, request: Request):
        with app.state.sessions.begin() as session:
            session.scalar(select(LoginGuard).where(LoginGuard.id == "admin").with_for_update())
            user = session.scalar(select(User).where(User.id == user_id, User.status != "deleted").with_for_update())
            if user is None:
                raise HTTPException(404, "Пользователь не найден")
            if user.is_bootstrap or user.id == request.state.user_id:
                raise HTTPException(409, "Нельзя менять роль основного администратора или свою роль")
            user.role = payload.role
            return {"user": user_metadata(user)}

    @router.delete("/api/users/{user_id}", dependencies=[Depends(admin_only)])
    def delete_user(user_id: str, request: Request):
        with app.state.sessions.begin() as session:
            session.scalar(select(LoginGuard).where(LoginGuard.id == "admin").with_for_update())
            user = session.scalar(select(User).where(User.id == user_id, User.status != "deleted").with_for_update())
            if user is None:
                raise HTTPException(404, "Пользователь не найден")
            if user.is_bootstrap or user.id == request.state.user_id:
                raise HTTPException(409, "Нельзя удалить основного администратора или себя")
            user.status, user.password_hash, user.invite_hash, user.invite_expires = "deleted", None, None, None
            session.execute(delete(AdminSession).where(AdminSession.user_id == user.id))
        return {"status": "ok"}

    @router.post("/api/auth/invitations/accept", dependencies=[Depends(public)])
    def accept_invite(payload: AcceptInvite):
        password_hash = hash_password(payload.password)
        with app.state.sessions.begin() as session:
            user = session.scalar(select(User).where(User.invite_hash == digest(payload.token)).with_for_update())
            if user is None or user.status != "invited" or not user.invite_expires or user.invite_expires <= time.time():
                raise HTTPException(400, "Приглашение недействительно или истекло")
            user.password_hash, user.status = password_hash, "active"
            user.invite_hash, user.invite_expires = None, None
            return {"login": user.login, "status": "ok"}

    return router
