from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import load_only
from ...access import integration_allowed, require_permission, client_visible
from ...models import Document
from ...schemas import serialize, public_result


def create_router(app, storage, policy=integration_allowed):
    router = APIRouter(tags=["Documents"])
    def visible_documents(request):
        return client_visible(select(Document), Document, request)

    @router.get("/documents", dependencies=[Depends(policy)])
    def documents(request: Request, page: int = Query(default=0, ge=0), pipeline_id: str | None = Query(default=None),
                  page_size: int = Query(default=50, ge=1, le=100), q: str = Query(default="", max_length=200)):
        require_permission(request, "history")
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
        require_permission(request, "results")
        with app.state.sessions() as session:
            row = session.scalar(visible_documents(request).where(Document.id == document_id))
            if row is None:
                raise HTTPException(404, "Документ не найден")
            payload = serialize(row, detail=True)
            if request.url.path.startswith("/api/v1/"):
                payload["result"] = public_result(row)
            return {"document": payload}

    return router
