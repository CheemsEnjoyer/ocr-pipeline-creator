import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from .policies import workspace_only
from ..db.domain.models import Document, SavedPipeline
from ..db.infra.repositories import now
from ..schema.api import FieldUpdate
from ..handler.storage import TemporaryFileResponse


def create_router(app, storage):
    router = APIRouter()


    @router.get("/api/history/pipelines", tags=["Documents"], dependencies=[Depends(workspace_only)])
    def history_pipelines():
        with app.state.sessions() as session:
            choices = {row.id: {"id": row.id, "name": row.config.get("name", row.id), "deleted": bool(row.deleted)} for row in session.scalars(select(SavedPipeline))}
            historical = session.execute(select(Document.pipeline_id, Document.pipeline_name).where(Document.pipeline_id.is_not(None)).distinct()).all()
            for pipeline_id, name in historical:
                choices.setdefault(pipeline_id, {"id": pipeline_id, "name": name, "deleted": True})
            return {"pipelines": sorted(choices.values(), key=lambda item: (item["name"], item["id"]))}


    @router.patch("/api/documents/{document_id}", tags=["Documents"], dependencies=[Depends(workspace_only)])
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

    @router.get("/api/documents/{document_id}/original", tags=["Documents"], dependencies=[Depends(workspace_only)])
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

    from .v1.documents import create_router as create_read_router
    router.include_router(create_read_router(app, storage, policy=workspace_only), prefix="/api")
    return router
