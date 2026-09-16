from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from ...access import integration_allowed
from ...models import SavedPipeline
from ...processing import Pipeline
from ...config import MAX_FILE_SIZE


def create_router(app, storage):
    router = APIRouter(tags=["Обработка"])
    def stored_pipeline(pipeline_id, request):
        if not request.state.user_id and pipeline_id not in request.state.pipeline_ids:
            raise HTTPException(403, "Ключу не разрешён этот пайплайн")
        with app.state.sessions() as session:
            row = session.get(SavedPipeline, pipeline_id)
            if row is None or row.deleted:
                raise HTTPException(404, "Пайплайн не найден")
            return Pipeline.model_validate(row.config)

    @router.post("/pipelines/{pipeline_id}/run", dependencies=[Depends(integration_allowed)])
    async def run_saved_pipeline(pipeline_id: str, request: Request, file: UploadFile = File(), background: bool = Query(default=False)):
        parsed = await run_in_threadpool(stored_pipeline, pipeline_id, request)
        return await process_file(file, parsed, request, pipeline_id, background)

    @router.post("/pipeline/run", dependencies=[Depends(integration_allowed)])
    async def run_pipeline(request: Request, file: UploadFile = File(), pipeline: str | None = Form(default=None), pipeline_id: str | None = Form(default=None), background: bool = Query(default=False)):
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

    async def process_file(file, parsed, request, pipeline_id=None, background=False):
        try:
            content = await file.read(MAX_FILE_SIZE + 1)
        finally:
            await file.close()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, "Максимальный размер файла — 20 МБ")
        filename = file.filename or "document"
        mime = file.content_type or "application/octet-stream"
        if background:
            prefix = request.url.path.rsplit("/pipeline", 1)[0]
            job_id = await run_in_threadpool(app.state.processing.submit, content, filename, mime, parsed, pipeline_id, request.state.api_key_id)
            payload = {"taskId": job_id, "status": "queued", "statusUrl": f"{prefix}/jobs/{job_id}"}
            return JSONResponse(payload, status_code=202, headers={"Location": payload["statusUrl"]})
        return await app.state.processing.run(app.state.client, content, filename, mime, parsed, pipeline_id, request.state.api_key_id)

    return router
