from pydantic import BaseModel, Field
import json
from .processing import Pipeline, result_schema


class InitTaskRequestDTO(BaseModel):
    task_code: str = Field(min_length=1, max_length=80, pattern=r"\S")
    document_type: str = Field(default="generic", min_length=1, max_length=80, pattern=r"\S")
    callback_url: str = Field(min_length=1, pattern=r"\S")
    document_link: str = Field(min_length=1, pattern=r"\S")


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


def serialize_public_pipeline(row):
    pipeline = Pipeline.model_validate(row.config)
    return {
        "id": row.id,
        "name": pipeline.name,
        "description": pipeline.description,
        "executionModes": [mode for mode, allowed in (("sync", pipeline.allow_sync), ("async", pipeline.allow_async)) if allowed],
        **({"asyncConcurrency": pipeline.async_concurrency} if pipeline.allow_async else {}),
        "resultSchema": result_schema(pipeline),
    }


def public_result(document):
    schema = document.result_schema
    structured = schema.get("type") == "object" if schema else bool(document.fields)
    return json.loads(document.result) if structured else document.result


class ChatRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    fields: list[dict[str, str]] = Field(default_factory=list)
    documentText: str = ""
    maxTokens: int = Field(default=2048, ge=1, le=128000)


