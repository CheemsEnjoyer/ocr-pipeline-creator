import os
from dataclasses import dataclass

MAX_FILE_SIZE = 20 * 1024 * 1024


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

    @classmethod
    def from_env(cls):
        settings = cls(
            timeout=positive_int("OCR_JOB_TIMEOUT_SECONDS", 600),
            soft_limit=positive_int("OCR_TASK_SOFT_LIMIT_SECONDS", 240),
            hard_limit=positive_int("OCR_TASK_HARD_LIMIT_SECONDS", 270),
            lease=positive_int("OCR_JOB_LEASE_SECONDS", 300),
            max_attempts=positive_int("OCR_JOB_MAX_ATTEMPTS", 3),
            retry_delay=positive_int("OCR_JOB_RETRY_DELAY_SECONDS", 10),
        )
        if not settings.soft_limit < settings.hard_limit < settings.lease:
            raise RuntimeError("Лимиты должны удовлетворять soft_limit < hard_limit < lease")
        return settings
