from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from ...access import integration_allowed
from ...models import Document, ProcessingJob, SavedPipeline
from ...repositories import add_outbox, now


def create_router(app, storage):
    router = APIRouter(tags=["Jobs"])
    @router.get("/jobs/{job_id}", dependencies=[Depends(integration_allowed)])
    def job_status(job_id: str, request: Request):
        with app.state.sessions() as session:
            job = session.get(ProcessingJob, job_id)
            if job is None or (not request.state.user_id and job.api_key_id != request.state.api_key_id):
                raise HTTPException(404, "Задача не найдена")
            payload = {"taskId": job.id, "status": job.status, "file": job.filename, "attempts": job.attempts}
            if job.status == "failed":
                payload["error"] = job.error
            elif job.status == "succeeded":
                document = session.get(Document, job.id)
                payload.update(text=document.text, result=document.result, documentId=document.id)
            return payload

    @router.post("/jobs/{job_id}/retry", dependencies=[Depends(integration_allowed)])
    def retry_job(job_id: str, request: Request):
        try:
            with app.state.sessions.begin() as session:
                query = select(ProcessingJob).where(ProcessingJob.id == job_id)
                if not request.state.user_id:
                    query = query.where(ProcessingJob.api_key_id == request.state.api_key_id)
                job = session.scalar(query.with_for_update(nowait=True))
                if job is None or (not request.state.user_id and job.api_key_id != request.state.api_key_id):
                    raise HTTPException(404, "Задача не найдена")
                if not request.state.user_id:
                    if job.pipeline_id not in request.state.pipeline_ids:
                        raise HTTPException(403, "Ключу больше не разрешён этот пайплайн")
                    pipeline = session.get(SavedPipeline, job.pipeline_id)
                    if pipeline is None or pipeline.deleted:
                        raise HTTPException(404, "Пайплайн не найден")
                if job.status not in {"queued", "failed"}:
                    raise HTTPException(409, "Задача уже выполняется или завершена")
                job.status, job.error, job.updated_at = "queued", None, now()
                job.generation += 1
                job.attempts, job.next_run_at, job.deadline_at = 0, 0, None
                job.lease_token, job.lease_until = None, None
                add_outbox(session, job)
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise HTTPException(409, "Задача уже выполняется") from error
            raise
        return JSONResponse({"taskId": job_id, "status": "queued"}, status_code=202)

    return router
