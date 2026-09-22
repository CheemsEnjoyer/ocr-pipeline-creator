import ipaddress
import logging
import os
import re
import socket
import time
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


RESOLVE_TTL = 60
_resolved = {}


def resolve(hostname):
    """Адреса хоста с короткой памятью, включая отрицательный ответ.

    Кэш здесь не оптимизация: без него каждая проверка адреса ждёт DNS, а имена,
    которые не разрешаются, ждут полного таймаута резолвера. TTL короткий, потому
    что проверка всё равно не спасает от смены записи между проверкой и запросом.
    """
    try:
        return ipaddress.ip_address(hostname) and [hostname]
    except ValueError:
        pass
    cached = _resolved.get(hostname)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(hostname, None)})
    except socket.gaierror:
        # Имя не разрешается — запрос всё равно не уйдёт, пусть падает на отправке.
        addresses = []
    _resolved[hostname] = (time.monotonic() + RESOLVE_TTL, addresses)
    return addresses


class UnsafeUrl(ValueError):
    """Адрес, по которому серверу ходить нельзя."""


def check_external_url(value, what="Адрес"):
    """Пропускает только http(s) на внешний хост.

    Ссылку на документ и адрес callback задаёт владелец ключа, а ходит по ним сервер.
    Без этой проверки ключ превращается в инструмент для запросов во внутреннюю сеть
    и к метаданным облака. Проверка не отменяет сетевых ограничений: DNS может
    смениться между проверкой и запросом, поэтому доступ наружу стоит резать и файрволом.
    """
    if os.getenv("OCR_ALLOW_PRIVATE_URLS", "").strip() == "1":
        return value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrl(f"{what} должен начинаться с http:// или https://")
    if not parts.hostname:
        raise UnsafeUrl(f"{what} не содержит хоста")
    for address in resolve(parts.hostname):
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrl(f"{what} указывает на внутренний адрес")
    return value
