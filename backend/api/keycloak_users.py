from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .policies import admin_only
from ..handler.keycloak_admin import KeycloakAdmin


class Invitation(BaseModel):
    login: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    role: Literal["admin", "user"] = "user"


class Role(BaseModel):
    role: Literal["admin", "user"]


def create_router(app, storage):
    router = APIRouter(tags=["Users"])

    @router.get("/api/users", dependencies=[Depends(admin_only)])
    def users():
        return {"users": KeycloakAdmin(app.state.keycloak).users()}

    @router.post("/api/users/invite", status_code=201, dependencies=[Depends(admin_only)])
    def invite(payload: Invitation):
        return KeycloakAdmin(app.state.keycloak).invite(payload.login, payload.name, payload.email, payload.role)

    @router.patch("/api/users/{user_id}", dependencies=[Depends(admin_only)])
    def update(user_id: str, payload: Role, request: Request):
        return KeycloakAdmin(app.state.keycloak).change(user_id, request.state.user_id, payload.role)

    @router.delete("/api/users/{user_id}", dependencies=[Depends(admin_only)])
    def remove(user_id: str, request: Request):
        return KeycloakAdmin(app.state.keycloak).change(user_id, request.state.user_id)

    return router
