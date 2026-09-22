"""Ошибки бизнес-логики.

Слои service, repositories и handler не знают про HTTP: они возбуждают эти
исключения, а слой API переводит их в ответ (см. обработчик в main.py).
Атрибут status — рекомендация для этого перевода, а не зависимость от FastAPI.
"""


class DomainError(Exception):
    status = 500
    transient = False

    def __init__(self, message, *, headers=None, transient=None):
        super().__init__(message)
        self.message = message
        self.headers = headers
        if transient is not None:
            self.transient = transient


class InvalidRequest(DomainError):
    status = 400


class NotAuthenticated(DomainError):
    status = 401


class NotFound(DomainError):
    status = 404


class InvalidDocument(DomainError):
    """Файл или конфигурация пайплайна не позволяют обработать документ."""
    status = 422


class LimitExceeded(DomainError):
    status = 429


class UpstreamError(DomainError):
    """Внешний сервис (OCR или LiteLLM) ответил ошибкой или неожиданным телом."""
    status = 502
    RETRYABLE = {408, 429, 500, 502, 503, 504}

    @classmethod
    def from_status(cls, message, status):
        """Повторять задачу имеет смысл только при временных ответах сервиса."""
        return cls(message, transient=status in cls.RETRYABLE)


class ConfigurationError(DomainError):
    status = 503


class ProcessingTimeout(DomainError):
    status = 504
