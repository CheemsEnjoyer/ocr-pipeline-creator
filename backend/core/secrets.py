"""Учётные данные администратора: хэши, отпечаток пароля и первичная настройка."""

import hashlib
import logging
import os
import secrets

from ..service.accounts import initialize_account
from ..service.throttle import LoginThrottle

PASSWORD_FILE = "admin-password.txt"
# Пароль, в отличие от ключа, бывает коротким, поэтому перебор ограничен.
MIN_PASSWORD_LENGTH = 8


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(login, password):
    # Медленный хэш: по отпечатку в таблице сессий пароль быстро не подобрать.
    return hashlib.scrypt(f"{login}\0{password}".encode("utf-8"), salt=b"ocr-flow-admin", n=2**14, r=8, p=1, dklen=32).hex()


def initialize_admin(app, storage):
    login = os.getenv("OCR_ADMIN_LOGIN", "").strip() or "admin"
    password = os.getenv("OCR_ADMIN_PASSWORD", "")
    source = "OCR_ADMIN_PASSWORD"
    if not password:
        path = storage / PASSWORD_FILE
        source = f"Файл {path}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            password = path.read_text(encoding="utf-8").strip()
        else:
            password = secrets.token_urlsafe(18)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(password + chr(10))
        logging.getLogger("uvicorn.error").info("Вход администратора: логин %s, пароль хранится в %s", login, path)
    if len(login) > 120:
        raise RuntimeError("OCR_ADMIN_LOGIN: логин должен быть не длиннее 120 символов")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"{source}: пароль администратора должен содержать не менее {MIN_PASSWORD_LENGTH} символов")
    app.state.admin_fingerprint = fingerprint(login, password)
    app.state.login_throttle = LoginThrottle(app.state.sessions)
    initialize_account(app, login, app.state.admin_fingerprint)
