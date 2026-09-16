from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from ...access import integration_allowed
from ...models import SavedPipeline
from ...schemas import serialize_pipeline


def create_router(app, storage):
    router = APIRouter(tags=["Pipelines"])
    @router.get("/pipelines", dependencies=[Depends(integration_allowed)])
    def list_pipelines(request: Request):
        with app.state.sessions() as session:
            query = select(SavedPipeline).where(SavedPipeline.deleted == 0)
            if not request.state.user_id:
                query = query.where(SavedPipeline.id.in_(request.state.pipeline_ids))
            rows = session.scalars(query.order_by(SavedPipeline.updated_at.desc(), SavedPipeline.id))
            return {"pipelines": [serialize_pipeline(row) for row in rows]}

    return router
