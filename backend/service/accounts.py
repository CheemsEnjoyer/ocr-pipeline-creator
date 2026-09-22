import hashlib
import secrets
from uuid import uuid4

from sqlalchemy import select

from ..db.domain.models import User, LoginGuard
from ..db.infra.repositories import now


def hash_password(password):
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32).hex()
    return f"scrypt${salt}${value}"


def verify_password(password, stored):
    try:
        algorithm, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


def session_hash(user):
    return user.password_hash if user.is_bootstrap else hashlib.sha256((user.password_hash or "").encode()).hexdigest()


def user_metadata(user):
    return {"id": user.id, "login": user.login, "name": user.name, "role": user.role, "status": user.status, "is_bootstrap": bool(user.is_bootstrap), "created_at": user.created_at}


def initialize_account(app, login, password_fingerprint):
    with app.state.sessions.begin() as session:
        session.scalar(select(LoginGuard).where(LoginGuard.id == "admin").with_for_update())
        user = session.scalar(select(User).where(User.is_bootstrap == 1))
        if user is None:
            user = User(id=str(uuid4()), login=login, name=login, role="admin", status="active", password_hash=password_fingerprint, is_bootstrap=1, created_at=now())
            session.add(user)
        else:
            user.login, user.password_hash = login, password_fingerprint
        session.flush()
        app.state.bootstrap_user_id = user.id
