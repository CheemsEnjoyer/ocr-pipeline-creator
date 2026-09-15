import logging
import os
import re
from urllib.parse import urlsplit, urlunsplit


def safe_url(value):
    if not value:
        return "неизвестен"
    try:
        parts = urlsplit(str(value))
        # Drop all user information, query strings and fragments, including signed URLs.
        host = parts.hostname
        if not host or parts.scheme not in {"http", "https", "socks5", "socks5h", "redis", "rediss", "postgresql"}:
            return "[адрес скрыт]"
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except (ValueError, TypeError):
        return "[адрес скрыт]"


def redact(value):
    text = str(value)
    text = re.sub(r"(?:https?|socks5h?|rediss?|postgresql(?:\+psycopg)?|s3)://[^\s\"'<>]+", lambda match: safe_url(match.group()), text)
    text = re.sub(r"([?&](?:code|state|id_token_hint|access_token|refresh_token)=)[^&\s\"']+", r"\1[скрыто]", text)
    for name, secret in os.environ.items():
        if any(word in name.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "ACCESS_KEY", "SESSION_KEY")) and len(secret) >= 4:
            text = text.replace(secret, "[скрыто]")
    return text


class SecretFilter(logging.Filter):
    def filter(self, record):
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            # Uvicorn's formatter unpacks its original five arguments.
            record.args = tuple(redact(value) if isinstance(value, str) else value for value in record.args)
            return True
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            import traceback
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return True


def configure_logging():
    for name in ("ocr", "ocr.worker", "ocr.dispatcher", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, SecretFilter) for item in logger.filters):
            logger.addFilter(SecretFilter())
