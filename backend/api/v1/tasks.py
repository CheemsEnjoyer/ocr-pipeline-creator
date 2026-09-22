from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from ..policies import integration_allowed, require_permission
from .processing import load_pipeline
from ...core.security import UnsafeUrl, check_external_url
from ...db.domain.models import ProcessingJob
from ...db.infra.repositories import now
from ...schema.api import CreateTaskRequest


def filename_from(url):
    """Имя файла берётся из ссылки: в контракте внешней системы его нет."""
    name = unquote(urlsplit(url).path).rsplit("/", 1)[-1].strip()
    return name[:200] or "document"


def create_router(app, storage):
    router = APIRouter(tags=["Tasks"])

    @router.post("/pipelines/{pipeline_id}/tasks", status_code=202, dependencies=[Depends(integration_allowed)])
    async def create_task(pipeline_id: str, payload: CreateTaskRequest, request: Request):
        """Принимает задачу от внешней учётной системы и ставит её в общую очередь.

        Файл не передаётся: воркер скачает его по document_link, а готовый результат
        уйдёт POST-запросом на callback_url. Опросить статус можно и по statusUrl.
        """
        require_permission(request, "run")
        parsed = await run_in_threadpool(load_pipeline, app, pipeline_id, request)
        if not parsed.allow_async:
            raise HTTPException(400, "Для этого пайплайна асинхронная обработка отключена")
        try:
            check_external_url(payload.document_link, "Ссылка на документ")
            check_external_url(payload.callback_url, "Адрес callback")
        except UnsafeUrl as error:
            raise HTTPException(400, str(error)) from error

        job_id, timestamp = str(uuid4()), now()
        job = ProcessingJob(
            id=job_id, status="queued", stage="queued",
            filename=filename_from(payload.document_link), mime_type=payload.content_type, size=0,
            original_key=None, source_url=payload.document_link,
            task_code=payload.task_code, callback_url=payload.callback_url,
            callback_status="pending", callback_attempts=0, callback_next_at=0,
            pipeline=parsed.model_dump(mode="json"), pipeline_id=pipeline_id,
            api_key_id=request.state.api_key_id, client_id=request.state.client_id,
            priority=parsed.priority, created_at=timestamp, updated_at=timestamp,
            generation=0, attempts=0, next_run_at=0,
        )
        try:
            await run_in_threadpool(app.state.processing.jobs.create, job)
        except IntegrityError as error:
            raise HTTPException(409, "Задача с таким task_code уже зарегистрирована") from error
        return {"task_code": payload.task_code, "taskId": job_id, "status": "queued",
                "statusUrl": f"/api/v1/jobs/{job_id}"}

    return router
