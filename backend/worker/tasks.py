from .celery_app import celery_app
from ..db.infra.engine import configured_database_url, open_database
from ..core.config import JobSettings, proxy_options
from ..core.security import configure_logging
from ..service.processing import ProcessingService, error_message, transient_error
from ..db.infra.repositories import JobRepository
from ..handler.storage import S3Storage


def execute_job(job_id, sessions, originals, transport=None, generation=None, settings=None):
    return ProcessingService(sessions, originals, settings).execute(job_id, generation, transport)


@celery_app.task(name="ocr.process_document")
def process_document(job_id, generation=None):
    configure_logging()
    proxy_options()
    engine, sessions = open_database(configured_database_url())
    originals = None
    try:
        originals = S3Storage.from_env()
        execute_job(job_id, sessions, originals, generation=generation)
    except Exception as error:
        repository = JobRepository(sessions, JobSettings.from_env())
        claimed = repository.claim(job_id, generation)
        if claimed is not None:
            repository.fail(claimed, error_message(error), transient_error(error))
    finally:
        if originals is not None:
            originals.close()
        engine.dispose()


def enqueue_job(job_id, generation=0, event_id=None, priority=5):
    process_document.apply_async(args=[job_id, generation], task_id=event_id or job_id, retry=False, priority=priority)
