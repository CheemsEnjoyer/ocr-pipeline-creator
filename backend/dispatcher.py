import logging
import signal
import threading

from .config import JobSettings
from .database import configured_database_url, open_database
from .repositories import OutboxRepository
from .security import configure_logging
from .tasks import enqueue_job

logger = logging.getLogger("ocr.dispatcher")


def dispatch_once(sessions, settings=None, publisher=enqueue_job, limit=100):
    repository = OutboxRepository(sessions, settings or JobSettings.from_env())
    repository.recover()
    count = 0
    for _ in range(limit):
        event = repository.claim()
        if event is None:
            break
        try:
            publisher(event.job_id, event.generation, event.id, event.priority)
        except Exception as error:
            logger.warning("Не удалось отправить событие %s: %s", event.id, type(error).__name__)
            repository.finish(event, False)
        else:
            repository.finish(event, True)
            count += 1
    return count


def main():
    configure_logging()
    settings = JobSettings.from_env()
    engine, sessions = open_database(configured_database_url())
    stopping = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stopping.set())
    try:
        while not stopping.is_set():
            try:
                dispatch_once(sessions, settings)
            except Exception as error:
                logger.error("Сбой диспетчера: %s", type(error).__name__)
            stopping.wait(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
