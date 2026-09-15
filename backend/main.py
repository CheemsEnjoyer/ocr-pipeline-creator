import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .access import initialize_admin, public, router as access_router, verify_policies
from .database import configured_database_url, open_database
from .processing import proxy_options
from .storage import OriginalNotFound, S3Storage, StorageError
from .migrate import migrate
from .services import ProcessingService
from .security import configure_logging, redact, safe_url
from .config import MAX_FILE_SIZE

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
logger = logging.getLogger("ocr")


def create_app(database_url=None, data_dir=None, transport=None):
    configure_logging()
    storage = Path(data_dir or os.getenv("OCR_DATA_DIR") or ROOT / "data").resolve()

    @asynccontextmanager
    async def lifespan(app):
        storage.mkdir(parents=True, exist_ok=True)
        engine, sessions = open_database(database_url or configured_database_url())
        originals = None
        try:
            # Idempotent: existing tables and documents are preserved on every restart.
            migrate(engine)
            app.state.sessions = sessions
            if app.state.auth_provider == "keycloak":
                from .keycloak import Keycloak, KeycloakSettings
                app.state.keycloak = Keycloak(KeycloakSettings.from_env(), sessions, transport)
            else:
                initialize_admin(app, storage)
            # PROXY_URL (or HTTP(S)_PROXY) is applied to the environment before the client is built,
            # so httpx sends the external OCR service and LiteLLM traffic through it.
            app.state.proxy = proxy_options()
            if app.state.proxy:
                logger.info("Внешние запросы идут через прокси %s", safe_url(app.state.proxy))
            originals = S3Storage.from_env()
            app.state.originals = originals
            app.state.processing = ProcessingService(sessions, originals)
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), transport=transport) as client:
                app.state.client = client
                yield
        finally:
            if getattr(app.state, "keycloak", None):
                app.state.keycloak.close()
            engine.dispose()
            if originals is not None:
                originals.close()

    app = FastAPI(title="OCR Pipeline Creator API", lifespan=lifespan)
    app.state.auth_provider = os.getenv("AUTH_PROVIDER", "local").strip()
    if app.state.auth_provider not in {"local", "keycloak"}:
        raise RuntimeError("AUTH_PROVIDER: local или keycloak")
    app.include_router(access_router)
    from .api.keycloak import router as keycloak_router
    app.include_router(keycloak_router)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        return JSONResponse({"error": redact(error.detail)}, status_code=error.status_code)

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

    @app.get("/api/health", dependencies=[Depends(public)])
    def health():
        with app.state.sessions() as session:
            session.execute(select(1))
        return {"status": "ok", "backend": "fastapi-sqlalchemy"}

    from .api import documents, litellm, pipelines, users, v1
    for module in (pipelines, documents, litellm, users, v1):
        app.include_router(module.create_router(app, storage))

    # Legacy URLs share v1 handlers; administrative routes keep their own policies.
    for module in (v1.pipelines, v1.jobs, v1.processing):
        app.include_router(module.create_router(app, storage), prefix="/api", include_in_schema=False)

    verify_policies(app)
    return app


app = create_app()
