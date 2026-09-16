from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import false, or_, select
from sqlalchemy.orm import load_only
from ...access import integration_allowed
from ...models import Document
from ...schemas import serialize


def create_router(app, storage, policy=integration_allowed):
    router = APIRouter(tags=["Documents"])
    def visible_documents(request):
        # Администратор видит всю историю, ключ интеграции — только документы, которые обработал сам.
        query = select(Document)
        if request.state.user_id:
            return query
        return query.where(Document.api_key_id == request.state.api_key_id) if request.state.api_key_id else query.where(false())

    @router.get("/documents", dependencies=[Depends(policy)])
    def documents(request: Request, page: int = Query(default=0, ge=0), pipeline_id: str | None = Query(default=None),
                  page_size: int = Query(default=50, ge=1, le=100), q: str = Query(default="", max_length=200)):
        with app.state.sessions() as session:
            query = visible_documents(request)
            if pipeline_id is not None:
                query = query.where(Document.pipeline_id == pipeline_id)
            if q.strip():
                query = query.where(or_(Document.filename.icontains(q.strip(), autoescape=True), Document.id.icontains(q.strip(), autoescape=True)))
            query = query.options(load_only(Document.id, Document.filename, Document.mime_type, Document.size,
                                            Document.pipeline_name, Document.pipeline_id, Document.created_at, Document.updated_at))
            rows = session.scalars(query.order_by(Document.created_at.desc(), Document.id.desc()).offset(page * page_size).limit(page_size + 1)).all()
            return {"documents": [serialize(row) for row in rows[:page_size]], "hasMore": len(rows) > page_size}

    @router.get("/documents/{document_id}", dependencies=[Depends(policy)])
    def document(document_id: str, request: Request):
        with app.state.sessions() as session:
            row = session.scalar(visible_documents(request).where(Document.id == document_id))
            if row is None:
                raise HTTPException(404, "Документ не найден")
            return {"document": serialize(row, detail=True)}

    return router
