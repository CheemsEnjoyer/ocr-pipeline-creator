import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from ..policies import integration_allowed, require_permission
from ...db.domain.models import SavedPipeline
from ...schema.pipeline import Pipeline
from ...core.config import MAX_FILE_SIZE


def load_pipeline(app, pipeline_id, request):
    """Пайплайн, если он существует и разрешён пришедшему ключу. Блокирующий вызов."""
    if not request.state.user_id and pipeline_id not in request.state.pipeline_ids:
        raise HTTPException(403, "Ключу не разрешён этот пайплайн")
    with app.state.sessions() as session:
        row = session.get(SavedPipeline, pipeline_id)
        if row is None or row.deleted:
            raise HTTPException(404, "Пайплайн не найден")
        return Pipeline.model_validate(row.config)


def create_router(app, storage):
    router = APIRouter(tags=["Processing"])

    def stored_pipeline(pipeline_id, request):
        return load_pipeline(app, pipeline_id, request)

    @router.post("/pipelines/{pipeline_id}/run", dependencies=[Depends(integration_allowed)])
    async def run_saved_pipeline(pipeline_id: str, request: Request, file: UploadFile = File(), background: bool | None = Query(default=None)):
        require_permission(request, "run")
        parsed = await run_in_threadpool(stored_pipeline, pipeline_id, request)
        return await process_file(file, parsed, request, pipeline_id, background)

    @router.post("/pipeline/run", dependencies=[Depends(integration_allowed)])
    async def run_pipeline(request: Request, file: UploadFile = File(), pipeline: str | None = Form(default=None), pipeline_id: str | None = Form(default=None), background: bool | None = Query(default=None)):
        require_permission(request, "run")
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
        return await process_file(file, parsed, request, pipeline_id or None, background)

    async def process_file(file, parsed, request, pipeline_id=None, background=None):
        use_background = background if background is not None else not parsed.allow_sync and parsed.allow_async
        if use_background and not parsed.allow_async:
            raise HTTPException(400, "Для этого пайплайна асинхронная обработка отключена")
        if not use_background and not parsed.allow_sync:
            raise HTTPException(400, "Для этого пайплайна синхронная обработка отключена")
        try:
            content = await file.read(MAX_FILE_SIZE + 1)
        finally:
            await file.close()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, "Максимальный размер файла — 20 МБ")
        filename = file.filename or "document"
        mime = file.content_type or "application/octet-stream"
        if use_background:
            prefix = request.url.path.rsplit("/pipeline", 1)[0]
            job_id = await run_in_threadpool(app.state.processing.submit, content, filename, mime, parsed, pipeline_id, request.state.api_key_id, request.state.client_id)
            payload = {"taskId": job_id, "status": "queued", "statusUrl": f"{prefix}/jobs/{job_id}"}
            return JSONResponse(payload, status_code=202, headers={"Location": payload["statusUrl"]})
        slot_id = await run_in_threadpool(app.state.processing.sync_capacity.acquire, request.state.client_id)
        try:
            payload = await app.state.processing.run(app.state.client, content, filename, mime, parsed, pipeline_id, request.state.api_key_id, request.state.client_id)
        finally:
            await run_in_threadpool(app.state.processing.sync_capacity.release, slot_id)
        if not request.state.user_id and "results" not in request.state.permissions:
            return {"file": filename, "documentId": payload["documentId"], "status": "succeeded"}
        if request.url.path.startswith("/api/v1/") and parsed.extraction and parsed.extraction.use_fields:
            payload["result"] = json.loads(payload["result"])
        return payload

    return router
