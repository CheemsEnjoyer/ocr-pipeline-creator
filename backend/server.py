import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .api.policies import public, verify_policies
from .core.config import ROOT
from .core.errors import DomainError
from .core.lifespan import build_lifespan
from .core.security import configure_logging, redact, safe_url
from .handler.storage import OriginalNotFound, StorageError

load_dotenv(ROOT / ".env")
logger = logging.getLogger("ocr")


def create_app(database_url=None, data_dir=None, transport=None):
    configure_logging()
    storage = Path(data_dir or os.getenv("OCR_DATA_DIR") or ROOT / "data").resolve()

    app = FastAPI(
        title="OCR Pipeline Creator API",
        lifespan=build_lifespan(storage, database_url, transport),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        # Схема описывает только /api/v1 — контракт выгрузки во внешние учётные системы.
        # Маршруты интерфейса администратора и рабочего пространства из неё исключены
        # (include_in_schema=False ниже): они работают, но в /api/docs не показываются.
        openapi_tags=[
            {"name": "Pipelines", "description": "List the pipelines available to the integration key."},
            {"name": "Processing", "description": "Submit a document for processing."},
            {"name": "Jobs", "description": "Check the status of background jobs and retry failed jobs."},
            {"name": "Documents", "description": "Fetch recognition results."},
        ],
        swagger_ui_parameters={"docExpansion": "none"},
    )
    app.state.auth_provider = os.getenv("AUTH_PROVIDER", "local").strip()
    if app.state.auth_provider not in {"local", "keycloak"}:
        raise RuntimeError("AUTH_PROVIDER: local или keycloak")
    from .api.auth import router as auth_router
    from .api.keys import router as keys_router
    from .api.keycloak import router as keycloak_router
    for shared in (auth_router, keys_router, keycloak_router):
        app.include_router(shared, include_in_schema=False)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        return JSONResponse({"error": redact(error.detail)}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(DomainError)
    async def domain_error(_request, error):
        # Единственное место, где ошибка бизнес-логики превращается в HTTP-ответ.
        return JSONResponse({"error": redact(error.message)}, status_code=error.status, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse({"error": "Некорректные параметры запроса"}, status_code=422)

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(_request, error):
        # 502 означает, что запрос не дошёл: без адреса и прокси в тексте причину не найти.
        target = safe_url(getattr(getattr(error, "request", None), "url", None))
        proxy = safe_url(app.state.proxy) if getattr(app.state, "proxy", None) else None
        logger.warning("Внешний запрос не удался: %s (адрес: %s, прокси: %s)", type(error).__name__, target or "неизвестен", proxy or "нет")
        detail = f"Сервис не ответил вовремя: {target}" if isinstance(error, httpx.TimeoutException) else f"Не удалось подключиться к {target}. Проверьте адрес в .env, прокси и доступ к сети."
        if proxy:
            detail += f" Запросы идут через прокси {proxy} — если сервис внутренний, добавьте его хост в NO_PROXY."
        return JSONResponse({"error": detail}, status_code=502)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request, error):
        logger.error("Database operation failed: %s", type(error).__name__)
        return JSONResponse({"error": "Не удалось сохранить или прочитать документ в базе"}, status_code=503)

    @app.exception_handler(OSError)
    async def file_error(_request, _error):
        return JSONResponse({"error": "Хранилище файлов недоступно. Проверьте место на диске и права на папку data."}, status_code=503)

    @app.exception_handler(StorageError)
    async def storage_error(_request, error):
        logger.error("S3 operation failed: %s", type(error.__cause__).__name__)
        return JSONResponse({"error": redact(str(error))}, status_code=404 if isinstance(error, OriginalNotFound) else 503)

    @app.get("/api/health", include_in_schema=False, dependencies=[Depends(public)])
    def health():
        with app.state.sessions() as session:
            session.execute(select(1))
        return {"status": "ok", "backend": "fastapi-sqlalchemy"}

    from .api import documents, litellm, pipelines, users, v1
    for module in (pipelines, documents, litellm, users):
        app.include_router(module.create_router(app, storage), include_in_schema=False)
    app.include_router(v1.create_router(app, storage))

    # Legacy URLs share v1 handlers; administrative routes keep their own policies.
    for module in (v1.pipelines, v1.jobs, v1.processing):
        app.include_router(module.create_router(app, storage), prefix="/api", include_in_schema=False)

    verify_policies(app)
    return app


app = create_app()
