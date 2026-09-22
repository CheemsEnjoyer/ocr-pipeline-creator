"""Контракты управления доступом: вход, клиенты интеграций и ключи."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


def serialize_key(key, client):
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "client_id": key.client_id,
            "client_name": client.name, "permissions": key.permissions, "pipeline_ids": client.pipeline_ids,
            "created_at": key.created_at, "revoked_at": key.revoked_at}


def serialize_client(client):
    return {"id": client.id, "name": client.name, "pipeline_ids": client.pipeline_ids, "created_at": client.created_at}
