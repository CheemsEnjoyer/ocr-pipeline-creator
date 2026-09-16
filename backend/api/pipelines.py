from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from ..access import admin_only
from ..models import SavedPipeline
from ..repositories import now
from ..schemas import PipelineImport, PipelineUpdate, serialize_pipeline


def create_router(app, storage):
    router = APIRouter(tags=["Pipelines"])

    @router.post("/api/pipelines", status_code=201, dependencies=[Depends(admin_only)])
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

    @router.post("/api/pipelines/import", dependencies=[Depends(admin_only)])
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

    @router.patch("/api/pipelines/{pipeline_id}", dependencies=[Depends(admin_only)])
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

    @router.delete("/api/pipelines/{pipeline_id}", dependencies=[Depends(admin_only)])
    def remove_pipeline(pipeline_id: str):
        with app.state.sessions() as session:
            row = session.get(SavedPipeline, pipeline_id)
            if row is None or row.deleted:
                raise HTTPException(404, "Пайплайн не найден")
            row.deleted = 1
            session.commit()
        return {"status": "ok"}

    return router
