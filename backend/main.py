import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .database import Base, Document, open_database
from .processing import Pipeline, api_url, complete, extract, litellm_config, ocr_services, proxy_options, recognize, result_fields

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
logger = logging.getLogger("ocr")
MAX_FILE_SIZE = 20 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def serialize(document, detail=False):
    names = ["id", "filename", "mime_type", "size", "pipeline_name", "created_at", "updated_at"]
    if detail:
        names += ["text", "result", "fields", "revision"]
    return {name: getattr(document, name) for name in names}


class FieldUpdate(BaseModel):
    fields: dict
    revision: int = Field(ge=0, strict=True)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    fields: list[dict[str, str]] = Field(default_factory=list)
    documentText: str = ""
    maxTokens: int = Field(default=2048, ge=1, le=128000)


def create_app(database_url=None, data_dir=None, transport=None):
    storage = Path(data_dir or os.getenv("OCR_DATA_DIR") or ROOT / "data").resolve()
    database_url = database_url or os.getenv("DATABASE_URL") or f"sqlite:///{(storage / 'ocr.sqlite3').as_posix()}"

    @asynccontextmanager
    async def lifespan(app):
        storage.mkdir(parents=True, exist_ok=True)
        (storage / "originals").mkdir(exist_ok=True)
        engine, sessions = open_database(database_url)
        try:
            # Idempotent: existing tables and documents are preserved on every restart.
            Base.metadata.create_all(engine)
            app.state.sessions = sessions
            # PROXY_URL (or HTTP(S)_PROXY) is applied to the environment before the client is built,
            # so httpx sends the external OCR service and LiteLLM traffic through it.
            app.state.proxy = proxy_options()
            if app.state.proxy:
                logger.info("Внешние запросы идут через прокси %s", app.state.proxy)
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), transport=transport) as client:
                app.state.client = client
                yield
        finally:
            engine.dispose()

    app = FastAPI(title="OCR Flow Studio API", lifespan=lifespan)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        return JSONResponse({"error": error.detail}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse({"error": "Некорректные параметры запроса"}, status_code=422)

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(_request, error):
        # 502 означает, что запрос не дошёл: без адреса и прокси в тексте причину не найти.
        target = getattr(getattr(error, "request", None), "url", None)
        proxy = getattr(app.state, "proxy", None)
        logger.warning("Внешний запрос не удался: %s: %s (адрес: %s, прокси: %s)", type(error).__name__, error, target or "неизвестен", proxy or "нет")
        detail = f"Сервис не ответил вовремя: {target}" if isinstance(error, httpx.TimeoutException) else f"Не удалось подключиться к {target}. Проверьте адрес в .env, прокси и доступ к сети."
        if proxy:
            detail += f" Запросы идут через прокси {proxy} — если сервис внутренний, добавьте его хост в NO_PROXY."
        return JSONResponse({"error": detail}, status_code=502)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request, error):
        logger.error("Database operation failed: %s", type(error).__name__)
        return JSONResponse({"error": "Не удалось сохранить или прочитать документ в базе"}, status_code=503)

    @app.exception_handler(OSError)
    async def file_error(_request, _error):
        return JSONResponse({"error": "Хранилище файлов недоступно. Проверьте место на диске и права на папку data."}, status_code=503)

    @app.get("/api/health")
    def health():
        with app.state.sessions() as session:
            session.execute(select(1))
        # Адреса из .env видны в health, чтобы не гадать, что именно прочитал сервер. Ключ не отдаём.
        return {"status": "ok", "backend": "fastapi-sqlalchemy", "proxy": app.state.proxy, "litellm": os.getenv("LITELLM_BASE_URL", "").strip() or None, "ocr_service": os.getenv("OCR_SERVICE_URL", "").strip() or None}

    @app.get("/api/documents")
    def documents(page: int = Query(default=0, ge=0)):
        with app.state.sessions() as session:
            rows = session.scalars(select(Document).order_by(Document.created_at.desc(), Document.id.desc()).offset(page * 50).limit(51)).all()
            return {"documents": [serialize(row) for row in rows[:50]], "hasMore": len(rows) > 50}

    @app.get("/api/documents/{document_id}")
    def document(document_id: str):
        with app.state.sessions() as session:
            row = session.get(Document, document_id)
            if row is None:
                raise HTTPException(404, "Документ не найден")
            return {"document": serialize(row, detail=True)}

    @app.patch("/api/documents/{document_id}")
    def update_fields(document_id: str, payload: FieldUpdate):
        if len(json.dumps(payload.fields, ensure_ascii=False)) > 1_000_000:
            raise HTTPException(400, "Поля документа слишком большие")
        timestamp = now()
        with app.state.sessions.begin() as session:
            outcome = session.execute(update(Document).where(Document.id == document_id, Document.revision == payload.revision).values(fields=payload.fields, updated_at=timestamp, revision=Document.revision + 1))
            if not outcome.rowcount:
                if session.get(Document, document_id) is None:
                    raise HTTPException(404, "Документ не найден")
                raise HTTPException(409, "Документ изменился в другой вкладке. Откройте его заново перед сохранением.")
        return {"revision": payload.revision + 1, "updated_at": timestamp}

    @app.get("/api/documents/{document_id}/original")
    def original(document_id: str, request: Request):
        with app.state.sessions() as session:
            row = session.get(Document, document_id)
            if row is None:
                raise HTTPException(404, "Документ не найден")
            path = (storage / "originals" / row.original_key).resolve()
            if not path.is_relative_to(storage / "originals") or not path.is_file():
                raise HTTPException(404, "Исходный файл не найден")
            inline = re.fullmatch(r"application/pdf|image/(png|jpeg|gif|webp|avif|bmp)", row.mime_type) and "download" not in request.query_params
            return FileResponse(path, filename=row.filename, media_type=row.mime_type, content_disposition_type="inline" if inline else "attachment", headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    def persist(content, filename, mime, pipeline_name, text, result):
        document_id = str(uuid4())
        path = storage / "originals" / document_id
        try:
            path.write_bytes(content)
            timestamp = now()
            with app.state.sessions.begin() as session:
                session.add(Document(id=document_id, filename=filename, mime_type=mime, size=len(content), pipeline_name=pipeline_name, original_key=document_id, text=text, result=result, fields=result_fields(result), created_at=timestamp, updated_at=timestamp, revision=0))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return document_id

    @app.post("/api/pipeline/run")
    async def run_pipeline(file: UploadFile = File(), pipeline: str = Form()):
        try:
            parsed = Pipeline.model_validate_json(pipeline)
        except ValidationError as error:
            raise HTTPException(400, "Некорректная конфигурация пайплайна") from error
        try:
            content = await file.read(MAX_FILE_SIZE + 1)
        finally:
            await file.close()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, "Максимальный размер файла — 20 МБ")
        filename = file.filename or "document"
        mime = file.content_type or "application/octet-stream"
        text = await recognize(app.state.client, parsed, content, filename, mime)
        result = await extract(app.state.client, parsed.extraction, text) if parsed.extraction else text
        document_id = await run_in_threadpool(persist, content, filename, mime, parsed.name, text, result)
        return {"file": filename, "text": text, "result": result, "documentId": document_id}

    @app.get("/api/ocr/services")
    def services():
        return {"services": ocr_services()}

    @app.get("/api/litellm/models")
    async def models():
        base, headers = litellm_config()
        response = await app.state.client.get(api_url(base, "models"), headers=headers)
        if not response.is_success:
            raise HTTPException(503, f"LiteLLM вернул HTTP {response.status_code}")
        try:
            names = {item["id"] for item in response.json().get("data", []) if isinstance(item.get("id"), str)}
            return {"models": sorted(names)}
        except (ValueError, TypeError, AttributeError) as error:
            raise HTTPException(502, "LiteLLM вернул некорректный список моделей") from error

    @app.post("/api/litellm/chat")
    async def chat(payload: ChatRequest):
        schema = {field.get("name", ""): {"type": "string", "description": field.get("description", "")} for field in payload.fields}
        result = await complete(app.state.client, {
            "model": payload.model, "temperature": 0, "max_tokens": payload.maxTokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{payload.prompt}\nВерни JSON с полями по схеме: {json.dumps(schema, ensure_ascii=False)}"},
                {"role": "user", "content": payload.documentText or "Текст документа появится после этапа OCR/извлечения."},
            ],
        })
        return {"model": payload.model, "result": result}

    return app


app = create_app()
