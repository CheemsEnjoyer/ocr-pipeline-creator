"""Жизненный цикл приложения: что поднимается на старте и закрывается на выходе."""

import logging
from contextlib import asynccontextmanager

import httpx

from ..db.infra.engine import configured_database_url, open_database
from ..db.migrate import migrate
from ..handler.storage import S3Storage
from ..service.processing import ProcessingService
from .config import proxy_options
from .secrets import initialize_admin
from .security import safe_url

logger = logging.getLogger("ocr")


def build_lifespan(storage, database_url=None, transport=None):
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
                from ..handler.keycloak import Keycloak, KeycloakSettings
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

    return lifespan
