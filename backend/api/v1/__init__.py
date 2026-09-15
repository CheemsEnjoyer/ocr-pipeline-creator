"""Version 1 of the integration API."""
from fastapi import APIRouter

from . import documents, jobs, pipelines, processing


def create_router(app, storage):
    router = APIRouter(prefix="/api/v1")
    for module in (pipelines, documents, jobs, processing):
        router.include_router(module.create_router(app, storage))
    return router
