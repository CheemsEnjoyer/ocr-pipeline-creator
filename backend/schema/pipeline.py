"""Конфигурация пайплайна.

Только описание данных и их правила: ни ввода-вывода, ни HTTP, ни базы.
Модель одинаково используется API, синхронной обработкой и воркером.
"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ExtractionField(BaseModel):
    name: str
    description: str = ""
    type: Literal["string", "number", "integer", "boolean", "object", "array"] = "string"
    fields: list["ExtractionField"] = Field(default_factory=list)


def validate_field_tree(fields, depth=1):
    names = [field.name for field in fields]
    if depth > 6 or not names or any(not name.strip() or name != name.strip() for name in names) or len(names) != len(set(names)):
        raise ValueError("Укажите непустые уникальные имена полей; максимум 6 уровней вложенности")
    for field in fields:
        if field.type in {"object", "array"}:
            validate_field_tree(field.fields, depth + 1)
        elif field.fields:
            raise ValueError("Вложенные поля допустимы только у объекта или списка объектов")


def fields_schema(fields, public=False):
    properties = {}
    for field in fields:
        schema = {"type": [field.type, "null"]}
        if not public:
            schema["description"] = field.description
        if field.type == "object":
            schema.update(fields_schema(field.fields, public))
            schema["type"] = ["object", "null"]
        elif field.type == "array":
            schema["items"] = fields_schema(field.fields, public)
        properties[field.name] = schema
    return {"type": "object", "properties": properties, "required": [field.name for field in fields], "additionalProperties": False}


class OCR(BaseModel):
    enabled: bool = True
    provider: Literal["litellm", "service"]
    temperature: float = Field(default=0, ge=0, le=2)
    model: str | None = None
    prompt: str | None = None
    url: HttpUrl | None = None
    # Поля формы конкретного OCR-сервиса (например model_name и force_ocr) — уходят вместе с файлом.
    options: dict[str, str] = Field(default_factory=dict)


class Extraction(BaseModel):
    mode: Literal["prompt", "fields"] = "fields"
    model: str = ""
    prompt_enabled: bool | None = None
    fields_enabled: bool | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=128000)
    prompt: str = ""
    fields: list[ExtractionField] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_field_names(self):
        if self.fields_enabled is not None:
            self.mode = "fields" if self.fields_enabled else "prompt"
        if self.active and not self.model.strip():
            raise ValueError("Выберите модель извлечения")
        if self.prompt_enabled is True and not self.prompt.strip():
            raise ValueError("Укажите промпт")
        if self.use_fields:
            validate_field_tree(self.fields)
        return self

    @property
    def use_fields(self):
        return self.fields_enabled if self.fields_enabled is not None else self.mode == "fields"

    @property
    def use_prompt(self):
        return self.prompt_enabled if self.prompt_enabled is not None else self.mode == "prompt"

    @property
    def active(self):
        return self.use_fields or self.use_prompt


class Pipeline(BaseModel):
    name: str = "Untitled"
    priority: int = Field(default=5, ge=0, le=9, strict=True)
    allow_sync: bool = True
    allow_async: bool = True
    async_concurrency: int = Field(default=1, ge=1, le=30, strict=True)
    source: Literal["scans", "document"]
    ocr: OCR | None = None
    extraction: Extraction | None = None

    @model_validator(mode="after")
    def at_least_one_execution_mode(self):
        if not self.allow_sync and not self.allow_async:
            raise ValueError("Разрешите хотя бы один режим выполнения")
        return self


def result_schema(pipeline):
    """Публичный контракт результата: JSON Schema полей или обычный текст."""
    extraction = pipeline.extraction
    return fields_schema(extraction.fields, public=True) if extraction and extraction.use_fields else {"type": "string"}
