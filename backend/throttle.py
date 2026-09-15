import time

from sqlalchemy import select

from .models import LoginGuard

MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 600


class LoginThrottle:
    """Serialize login checks and count failures across every API process in PostgreSQL."""
    def __init__(self, sessions):
        self.sessions = sessions

    def verify(self, check):
        with self.sessions.begin() as session:
            guard = session.scalar(select(LoginGuard).where(LoginGuard.id == "admin").with_for_update())
            if guard is None:
                raise RuntimeError("Login guard is missing: run database migrations")
            moment = time.time()
            failures = [item for item in guard.failures if moment - item < FAILED_LOGIN_WINDOW]
            if len(failures) >= MAX_FAILED_LOGINS:
                guard.failures = failures
                return False, max(1, FAILED_LOGIN_WINDOW - (moment - failures[0]))
            accepted = check()
            guard.failures = [] if accepted else [*failures, moment]
            return accepted, 0
