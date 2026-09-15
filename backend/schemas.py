from pydantic import BaseModel, Field
from .processing import Pipeline


def serialize(document, detail=False):
    names = ["id", "filename", "mime_type", "size", "pipeline_name", "pipeline_id", "created_at", "updated_at"]
    if detail:
        names += ["text", "result", "fields", "revision"]
    return {name: getattr(document, name) for name in names}


class FieldUpdate(BaseModel):
    fields: dict
    revision: int = Field(ge=0, strict=True)



class PipelineImport(Pipeline):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class PipelineUpdate(Pipeline):
    id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


def serialize_pipeline(row):
    return {**row.config, "id": row.id, "createdAt": row.created_at, "updatedAt": row.updated_at}


class ChatRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    fields: list[dict[str, str]] = Field(default_factory=list)
    documentText: str = ""
    maxTokens: int = Field(default=2048, ge=1, le=128000)


