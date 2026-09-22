from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from ..policies import integration_allowed
from ...db.domain.models import SavedPipeline
from ...schema.api import serialize_pipeline, serialize_public_pipeline


def create_router(app, storage):
    router = APIRouter(tags=["Pipelines"])
    @router.get("/pipelines", dependencies=[Depends(integration_allowed)])
    def list_pipelines(request: Request):
        with app.state.sessions() as session:
            query = select(SavedPipeline).where(SavedPipeline.deleted == 0)
            if not request.state.user_id:
                query = query.where(SavedPipeline.id.in_(request.state.pipeline_ids))
            rows = session.scalars(query.order_by(SavedPipeline.updated_at.desc(), SavedPipeline.id))
            serializer = serialize_public_pipeline if request.url.path.startswith("/api/v1/") or not request.state.user_id else serialize_pipeline
            return {"pipelines": [serializer(row) for row in rows]}

    return router
