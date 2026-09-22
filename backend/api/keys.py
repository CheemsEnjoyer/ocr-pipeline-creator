"""Клиенты интеграций и их API-ключи."""

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..core.secrets import digest
from ..db.domain.models import APIKey, IntegrationClient, SavedPipeline
from ..db.infra.repositories import now
from ..schema.access import ClientSettings, KeySettings, serialize_client, serialize_key
from .policies import admin_only

router = APIRouter()


def validate_settings(session, payload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название клиента")
    ids = list(dict.fromkeys(payload.pipeline_ids))
    available = set(session.scalars(select(SavedPipeline.id).where(SavedPipeline.id.in_(ids), SavedPipeline.deleted == 0)))
    if set(ids) != available:
        raise HTTPException(422, "Один из выбранных пайплайнов удалён или не существует")
    return name, ids


def key_settings(session, payload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название ключа")
    client = session.get(IntegrationClient, payload.client_id)
    if client is None:
        raise HTTPException(422, "Выберите существующего клиента")
    return name, client, list(dict.fromkeys(payload.permissions))


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@router.get("/api/clients", tags=["API Clients"], dependencies=[Depends(admin_only)])
def list_clients(request: Request):
    with request.app.state.sessions() as session:
        return {"clients": [serialize_client(row) for row in session.scalars(select(IntegrationClient).order_by(IntegrationClient.created_at.desc(), IntegrationClient.id))]}


@router.post("/api/clients", status_code=201, tags=["API Clients"], dependencies=[Depends(admin_only)])
def create_client(payload: ClientSettings, request: Request):
    with request.app.state.sessions.begin() as session:
        name, ids = validate_settings(session, payload)
        client = IntegrationClient(id=str(uuid4()), name=name, pipeline_ids=ids, created_at=now())
        session.add(client)
        return {"client": serialize_client(client)}


@router.patch("/api/clients/{client_id}", tags=["API Clients"], dependencies=[Depends(admin_only)])
def update_client(client_id: str, payload: ClientSettings, request: Request):
    with request.app.state.sessions.begin() as session:
        client = session.get(IntegrationClient, client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        client.name, client.pipeline_ids = validate_settings(session, payload)
        return {"client": serialize_client(client)}


@router.get("/api/keys", tags=["API Keys"], dependencies=[Depends(admin_only)])
def list_keys(request: Request):
    with request.app.state.sessions() as session:
        rows = session.execute(select(APIKey, IntegrationClient).join(IntegrationClient).order_by(APIKey.created_at.desc(), APIKey.id))
        return {"keys": [serialize_key(key, client) for key, client in rows]}


@router.post("/api/keys", status_code=201, tags=["API Keys"], dependencies=[Depends(admin_only)])
def create_key(payload: KeySettings, request: Request):
    token = "ocr_" + secrets.token_urlsafe(32)
    with request.app.state.sessions() as session:
        name, client, permissions = key_settings(session, payload)
        key = APIKey(id=str(uuid4()), name=name, token_hash=digest(token), prefix=token[:12], client_id=client.id, permissions=permissions, created_at=timestamp())
        session.add(key)
        session.commit()
        return {"key": serialize_key(key, client), "token": token}


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
        return {"key": serialize_key(key, client)}


@router.delete("/api/keys/{key_id}", tags=["API Keys"], dependencies=[Depends(admin_only)])
def revoke_key(key_id: str, request: Request):
    with request.app.state.sessions() as session:
        key = session.get(APIKey, key_id)
        if key is None:
            raise HTTPException(404, "Ключ не найден")
        key.revoked_at = key.revoked_at or timestamp()
        session.commit()
    return {"status": "ok"}
