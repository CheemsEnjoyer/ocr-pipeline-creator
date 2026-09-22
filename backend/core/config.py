import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .security import safe_url

# Корень репозитория: единственное место, где глубина файла превращается в путь.
ROOT = Path(__file__).resolve().parents[2]
MAX_FILE_SIZE = 20 * 1024 * 1024
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
PROXY_SCHEMES = ("http://", "https://", "socks5://", "socks5h://")

logger = logging.getLogger("ocr")


def normalized_proxy(value):
    # Corporate Windows environments sometimes supply proxy addresses without a scheme.
    value = (value or "").strip()
    if not value:
        return None
    return value if "://" in value else f"http://{value}"


def proxy_options():
    """PROXY_URL is the single knob for the corporate proxy; HTTP(S)_PROXY keep working as a fallback.

    The value is written back into the standard proxy variables, so httpx routes every outgoing
    request (external OCR service and LiteLLM alike) through it while still honouring NO_PROXY.
    """
    for name in PROXY_VARIABLES:
        value = normalized_proxy(os.getenv(name))
        if value:
            os.environ[name] = value
    proxy = normalized_proxy(os.getenv("PROXY_URL"))
    if proxy and not proxy.startswith(PROXY_SCHEMES):
        logger.warning("PROXY_URL=%s пропущен: поддерживаются схемы http, https, socks5.", safe_url(proxy))
        return None
    if proxy:
        for name in PROXY_VARIABLES:
            os.environ[name] = proxy
    return proxy


def positive_int(name, default):
    value = int(os.getenv(name) or default)
    if value < 1:
        raise RuntimeError(f"{name} должен быть положительным числом")
    return value


@dataclass(frozen=True)
class JobSettings:
    timeout: int = 600
    soft_limit: int = 240
    hard_limit: int = 270
    lease: int = 300
    max_attempts: int = 3
    retry_delay: int = 10
    client_active_limit: int = 10
    sync_global_limit: int = 10
    sync_client_limit: int = 4

    @classmethod
    def from_env(cls):
        settings = cls(
            timeout=positive_int("OCR_JOB_TIMEOUT_SECONDS", 600),
            soft_limit=positive_int("OCR_TASK_SOFT_LIMIT_SECONDS", 240),
            hard_limit=positive_int("OCR_TASK_HARD_LIMIT_SECONDS", 270),
            lease=positive_int("OCR_JOB_LEASE_SECONDS", 300),
            max_attempts=positive_int("OCR_JOB_MAX_ATTEMPTS", 3),
            retry_delay=positive_int("OCR_JOB_RETRY_DELAY_SECONDS", 10),
            client_active_limit=positive_int("OCR_CLIENT_ACTIVE_JOB_LIMIT", 10),
            sync_global_limit=positive_int("OCR_GLOBAL_SYNC_LIMIT", 10),
            sync_client_limit=positive_int("OCR_CLIENT_SYNC_LIMIT", 4),
        )
        if not settings.soft_limit < settings.hard_limit < settings.lease:
            raise RuntimeError("Лимиты должны удовлетворять soft_limit < hard_limit < lease")
        if settings.sync_client_limit > settings.sync_global_limit:
            raise RuntimeError("OCR_CLIENT_SYNC_LIMIT не может превышать OCR_GLOBAL_SYNC_LIMIT")
        return settings
