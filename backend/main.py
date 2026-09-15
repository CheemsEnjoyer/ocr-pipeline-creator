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
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import false, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .access import admin_only, initialize_admin, integration_allowed, public, router as access_router, verify_policies
from .database import Base, Document, SavedPipeline, open_database, upgrade_schema
from .processing import Pipeline, api_url, complete, extract, litellm_config, proxy_options, recognize, result_fields
from .storage import OriginalNotFound, S3Storage, StorageError, TemporaryFileResponse

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
logger = logging.getLogger("ocr")
MAX_FILE_SIZE = 20 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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


def create_app(database_url=None, data_dir=None, transport=None):
    storage = Path(data_dir or os.getenv("OCR_DATA_DIR") or ROOT / "data").resolve()
    database_url = database_url or os.getenv("DATABASE_URL") or f"sqlite:///{(storage / 'ocr.sqlite3').as_posix()}"

    @asynccontextmanager
    async def lifespan(app):
        storage.mkdir(parents=True, exist_ok=True)
        engine, sessions = open_database(database_url)
        originals = None
        try:
            # Idempotent: existing tables and documents are preserved on every restart.
            Base.metadata.create_all(engine)
            upgrade_schema(engine)
            app.state.sessions = sessions
            initialize_admin(app, storage)
            # PROXY_URL (or HTTP(S)_PROXY) is applied to the environment before the client is built,
            # so httpx sends the external OCR service and LiteLLM traffic through it.
            app.state.proxy = proxy_options()
            if app.state.proxy:
                logger.info("Внешние запросы идут через прокси %s", app.state.proxy)
            originals = S3Storage.from_env()
            app.state.originals = originals
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), transport=transport) as client:
                app.state.client = client
                yield
        finally:
            engine.dispose()
            if originals is not None:
                originals.close()

    app = FastAPI(title="OCR Flow Studio API", lifespan=lifespan)
    app.include_router(access_router)

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

    @app.exception_handler(StorageError)
    async def storage_error(_request, error):
        logger.error("S3 operation failed: %s", type(error.__cause__).__name__)
        return JSONResponse({"error": str(error)}, status_code=404 if isinstance(error, OriginalNotFound) else 503)

    @app.get("/api/health", dependencies=[Depends(public)])
    def health():
        with app.state.sessions() as session:
            session.execute(select(1))
        # Адреса из .env видны в health, чтобы не гадать, что именно прочитал сервер. Ключ не отдаём.
        return {"status": "ok", "backend": "fastapi-sqlalchemy"}

    # /api/v1 — версионированный API интеграций. Пути без версии остаются для интерфейса
    # и уже подключённых систем; обработчики у них общие.
    @app.get("/api/v1/pipelines", dependencies=[Depends(integration_allowed)])
    @app.get("/api/pipelines", dependencies=[Depends(integration_allowed)])
    def list_pipelines(request: Request):
        with app.state.sessions() as session:
            query = select(SavedPipeline).where(SavedPipeline.deleted == 0)
            if not request.state.is_admin:
                query = query.where(SavedPipeline.id.in_(request.state.pipeline_ids))
            rows = session.scalars(query.order_by(SavedPipeline.updated_at.desc(), SavedPipeline.id))
            return {"pipelines": [serialize_pipeline(row) for row in rows]}

    @app.post("/api/pipelines", status_code=201, dependencies=[Depends(admin_only)])
    def create_pipeline(payload: PipelineImport):
        timestamp = now()
        with app.state.sessions() as session:
            if session.get(SavedPipeline, payload.id) is not None:
                raise HTTPException(409, "Этот ID пайплайна уже занят. Укажите другой ID.")
            row = SavedPipeline(id=payload.id, config=payload.model_dump(mode="json", exclude={"id"}), created_at=timestamp, updated_at=timestamp)
            session.add(row)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise HTTPException(409, "Этот ID пайплайна уже занят. Укажите другой ID.") from error
            return {"pipeline": serialize_pipeline(row)}

    @app.post("/api/pipelines/import", dependencies=[Depends(admin_only)])
    def import_pipelines(payload: list[PipelineImport]):
        # Import legacy browser configurations only once; never overwrite server edits
        # or resurrect a pipeline deleted from another browser.
        timestamp = now()
        with app.state.sessions() as session:
            for item in payload:
                if session.get(SavedPipeline, item.id) is None:
                    session.add(SavedPipeline(id=item.id, config=item.model_dump(mode="json", exclude={"id"}), created_at=timestamp, updated_at=timestamp))
                    session.flush()
            session.commit()
        return {"status": "ok"}

    @app.patch("/api/pipelines/{pipeline_id}", dependencies=[Depends(admin_only)])
    def update_pipeline(pipeline_id: str, payload: PipelineUpdate):
        with app.state.sessions() as session:
            row = session.get(SavedPipeline, pipeline_id)
            if row is None or row.deleted:
                raise HTTPException(404, "Пайплайн не найден")
            if payload.id is not None and payload.id != pipeline_id:
                raise HTTPException(400, "ID сохранённого пайплайна нельзя изменить")
            row.config = payload.model_dump(mode="json", exclude={"id"})
            row.updated_at = now()
            session.commit()
            return {"pipeline": serialize_pipeline(row)}

    @app.delete("/api/pipelines/{pipeline_id}", dependencies=[Depends(admin_only)])
    def remove_pipeline(pipeline_id: str):
        with app.state.sessions() as session:
            row = session.get(SavedPipeline, pipeline_id)
            if row is None or row.deleted:
                raise HTTPException(404, "Пайплайн не найден")
            row.deleted = 1
            session.commit()
        return {"status": "ok"}

    def visible_documents(request):
        # Администратор видит всю историю, ключ интеграции — только документы, которые обработал сам.
        query = select(Document)
        if request.state.is_admin:
            return query
        return query.where(Document.api_key_id == request.state.api_key_id) if request.state.api_key_id else query.where(false())

    @app.get("/api/v1/documents", dependencies=[Depends(integration_allowed)])
    @app.get("/api/documents", dependencies=[Depends(admin_only)])
    def documents(request: Request, page: int = Query(default=0, ge=0)):
        with app.state.sessions() as session:
            rows = session.scalars(visible_documents(request).order_by(Document.created_at.desc(), Document.id.desc()).offset(page * 50).limit(51)).all()
            return {"documents": [serialize(row) for row in rows[:50]], "hasMore": len(rows) > 50}

    @app.get("/api/v1/documents/{document_id}", dependencies=[Depends(integration_allowed)])
    @app.get("/api/documents/{document_id}", dependencies=[Depends(admin_only)])
    def document(document_id: str, request: Request):
        with app.state.sessions() as session:
            row = session.scalar(visible_documents(request).where(Document.id == document_id))
            if row is None:
                raise HTTPException(404, "Документ не найден")
            return {"document": serialize(row, detail=True)}

    @app.patch("/api/documents/{document_id}", dependencies=[Depends(admin_only)])
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

    @app.get("/api/documents/{document_id}/original", dependencies=[Depends(admin_only)])
    def original(document_id: str, request: Request):
        with app.state.sessions() as session:
            row = session.get(Document, document_id)
            if row is None:
                raise HTTPException(404, "Документ не найден")
            inline = re.fullmatch(r"application/pdf|image/(png|jpeg|gif|webp|avif|bmp)", row.mime_type) and "download" not in request.query_params
            if row.original_key.startswith("s3:"):
                path = app.state.originals.download(row.original_key)
                response_type = TemporaryFileResponse
            else:
                # Existing local originals remain readable; all new uploads go to S3.
                path = (storage / "originals" / row.original_key).resolve()
                if not path.is_relative_to(storage / "originals") or not path.is_file():
                    raise HTTPException(404, "Исходный файл не найден")
                response_type = FileResponse
            return response_type(path, filename=row.filename, media_type=row.mime_type, content_disposition_type="inline" if inline else "attachment", headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    def persist(content, filename, mime, pipeline_name, text, result, pipeline_id=None, api_key_id=None, plain_text=False):
        document_id = str(uuid4())
        original_key = app.state.originals.put(document_id, content, mime)
        try:
            timestamp = now()
            with app.state.sessions.begin() as session:
                session.add(Document(id=document_id, filename=filename, mime_type=mime, size=len(content), pipeline_name=pipeline_name, original_key=original_key, text=text, result=result, fields={} if plain_text else result_fields(result), created_at=timestamp, updated_at=timestamp, revision=0, pipeline_id=pipeline_id, api_key_id=api_key_id))
        except Exception:
            try:
                app.state.originals.delete(original_key)
            except StorageError:
                logger.error("Не удалось удалить объект S3 после ошибки записи в базу: %s", original_key)
            raise
        return document_id

    def stored_pipeline(pipeline_id, request):
        if not request.state.is_admin and pipeline_id not in request.state.pipeline_ids:
            raise HTTPException(403, "Ключу не разрешён этот пайплайн")
        with app.state.sessions() as session:
            row = session.get(SavedPipeline, pipeline_id)
            if row is None or row.deleted:
                raise HTTPException(404, "Пайплайн не найден")
            return Pipeline.model_validate(row.config)

    @app.post("/api/v1/pipelines/{pipeline_id}/run", dependencies=[Depends(integration_allowed)])
    @app.post("/api/pipelines/{pipeline_id}/run", dependencies=[Depends(integration_allowed)])
    async def run_saved_pipeline(pipeline_id: str, request: Request, file: UploadFile = File()):
        parsed = await run_in_threadpool(stored_pipeline, pipeline_id, request)
        return await process_file(file, parsed, request, pipeline_id)

    @app.post("/api/v1/pipeline/run", dependencies=[Depends(integration_allowed)])
    @app.post("/api/pipeline/run", dependencies=[Depends(integration_allowed)])
    async def run_pipeline(request: Request, file: UploadFile = File(), pipeline: str | None = Form(default=None), pipeline_id: str | None = Form(default=None)):
        if pipeline is not None and not request.state.is_admin:
            raise HTTPException(403, "Передайте pipeline_id: ключ интеграции не может менять конфигурацию")
        if pipeline_id and pipeline is not None:
            raise HTTPException(400, "Передайте только pipeline_id или pipeline")
        if pipeline_id:
            parsed = await run_in_threadpool(stored_pipeline, pipeline_id, request)
        elif pipeline is not None and request.state.is_admin:
            try:
                parsed = Pipeline.model_validate_json(pipeline)
            except ValidationError as error:
                raise HTTPException(400, "Некорректная конфигурация пайплайна") from error
        else:
            raise HTTPException(400, "Укажите pipeline_id")
        return await process_file(file, parsed, request, pipeline_id or None)

    async def process_file(file, parsed, request, pipeline_id=None):
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
        document_id = await run_in_threadpool(persist, content, filename, mime, parsed.name, text, result, pipeline_id, request.state.api_key_id, bool(parsed.extraction and parsed.extraction.mode == "prompt"))
        return {"file": filename, "text": text, "result": result, "documentId": document_id}

    @app.get("/api/litellm/models", dependencies=[Depends(admin_only)])
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

    @app.post("/api/litellm/chat", dependencies=[Depends(admin_only)])
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

    verify_policies(app)
    return app


app = create_app()
