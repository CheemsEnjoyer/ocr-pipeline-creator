from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from ..policies import client_visible, integration_allowed, require_permission
from ...db.domain.models import Document, ProcessingJob
from ...db.infra.repositories import add_outbox, ensure_client_job_capacity, now
from ...schema.api import public_result


def create_router(app, storage):
    router = APIRouter(tags=["Jobs"])
    @router.get("/jobs/{job_id}", dependencies=[Depends(integration_allowed)])
    def job_status(job_id: str, request: Request):
        require_permission(request, "results")
        with app.state.sessions() as session:
            job = session.scalar(client_visible(select(ProcessingJob).where(ProcessingJob.id == job_id), ProcessingJob, request))
            if job is None:
                raise HTTPException(404, "Задача не найдена")
            payload = {"taskId": job.id, "status": job.status, "stage": job.stage, "file": job.filename, "attempts": job.attempts}
            if job.failed_stage:
                payload["failedStage"] = job.failed_stage
            if job.status == "failed":
                payload["error"] = job.error
            elif job.status == "succeeded":
                document = session.get(Document, job.id)
                payload.update(text=document.text, result=public_result(document) if request.url.path.startswith("/api/v1/") else document.result, documentId=document.id)
            return payload

    @router.post("/jobs/{job_id}/retry", dependencies=[Depends(integration_allowed)])
    def retry_job(job_id: str, request: Request):
        require_permission(request, "run")
        try:
            with app.state.sessions.begin() as session:
                query = client_visible(select(ProcessingJob).where(ProcessingJob.id == job_id), ProcessingJob, request)
                job = session.scalar(query.with_for_update(nowait=True))
                if job is None:
                    raise HTTPException(404, "Задача не найдена")
                if job.status not in {"queued", "failed"}:
                    raise HTTPException(409, "Задача уже выполняется или завершена")
                ensure_client_job_capacity(session, job.client_id, app.state.processing.settings.client_active_limit, job.id)
                job.status, job.stage, job.failed_stage, job.error, job.updated_at = "queued", "queued", None, None, now()
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
