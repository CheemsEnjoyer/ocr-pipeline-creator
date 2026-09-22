import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update

from ...core.errors import LimitExceeded, NotAuthenticated
from ..domain.models import IntegrationClient, ProcessingCapacity, ProcessingJob, SavedPipeline, SyncProcessingSlot, TaskOutbox


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def add_outbox(session, job):
    session.add(TaskOutbox(id=str(uuid4()), job_id=job.id, generation=job.generation or 0,
                           priority=job.priority, next_attempt_at=job.next_run_at or 0))


def ensure_client_job_capacity(session, client_id, limit, exclude_job_id=None):
    if client_id is None:
        return
    # One client-row lock serializes submissions from every key and API instance.
    if session.scalar(select(IntegrationClient.id).where(IntegrationClient.id == client_id).with_for_update()) is None:
        raise NotAuthenticated("Клиент API-ключа не найден")
    query = select(func.count()).select_from(ProcessingJob).where(
        ProcessingJob.client_id == client_id,
        ProcessingJob.status.in_(("queued", "processing")),
    )
    if exclude_job_id is not None:
        query = query.where(ProcessingJob.id != exclude_job_id)
    if session.scalar(query) >= limit:
        raise LimitExceeded(f"У клиента уже {limit} активных задач. Дождитесь завершения одной из них.", headers={"Retry-After": "5"})


class DocumentRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    def save(self, document):
        with self.sessions.begin() as session:
            session.add(document)


class SyncCapacityRepository:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    def acquire(self, client_id=None, clock=None):
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            # One row serializes the global and per-client counters across API instances.
            capacity = session.scalar(select(ProcessingCapacity).where(ProcessingCapacity.id == "sync").with_for_update())
            if capacity is None:
                capacity = ProcessingCapacity(id="sync")
                session.add(capacity)
                session.flush()
            session.execute(delete(SyncProcessingSlot).where(SyncProcessingSlot.expires_at <= clock))
            if session.scalar(select(func.count()).select_from(SyncProcessingSlot)) >= self.settings.sync_global_limit:
                raise LimitExceeded(f"Одновременно обрабатывается максимум {self.settings.sync_global_limit} синхронных документов.", headers={"Retry-After": "5"})
            if client_id is not None:
                client_running = session.scalar(select(func.count()).select_from(SyncProcessingSlot).where(SyncProcessingSlot.client_id == client_id))
                if client_running >= self.settings.sync_client_limit:
                    raise LimitExceeded(f"У клиента уже {self.settings.sync_client_limit} синхронных документа в обработке.", headers={"Retry-After": "5"})
            slot_id = str(uuid4())
            session.add(SyncProcessingSlot(id=slot_id, client_id=client_id, expires_at=clock + self.settings.timeout + 60))
            return slot_id

    def release(self, slot_id):
        with self.sessions.begin() as session:
            session.execute(delete(SyncProcessingSlot).where(SyncProcessingSlot.id == slot_id))


class JobRepository:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    def create(self, job):
        with self.sessions.begin() as session:
            ensure_client_job_capacity(session, job.client_id, self.settings.client_active_limit)
            session.add(job)
            add_outbox(session, job)

    def claim(self, job_id, generation=None, clock=None):
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
            if job is None or job.status in {"succeeded", "failed"}:
                return None
            if generation is not None and generation != job.generation:
                return None
            if job.next_run_at > clock or (job.status == "processing" and job.lease_until and job.lease_until > clock):
                return None
            if (job.deadline_at and job.deadline_at <= clock) or job.attempts >= self.settings.max_attempts:
                job.status, job.error, job.updated_at = "failed", "Превышен лимит времени или попыток обработки", now()
                job.failed_stage, job.stage = job.stage, "failed"
                job.lease_token, job.lease_until = None, None
                return None
            # Лимит одновременных задач задаётся пайплайном, поэтому применим он только к
            # задачам сохранённого пайплайна: инлайновые конфигурации группировать не по чему.
            if job.pipeline_id is not None:
                concurrency = job.pipeline.get("async_concurrency", 1)
                # The pipeline-row lock serializes capacity checks across workers.
                pipeline = session.scalar(select(SavedPipeline).where(SavedPipeline.id == job.pipeline_id).with_for_update())
                if pipeline is not None:
                    concurrency = pipeline.config.get("async_concurrency", concurrency)
                running = session.scalar(select(func.count()).select_from(ProcessingJob).where(
                    ProcessingJob.pipeline_id == job.pipeline_id,
                    ProcessingJob.status == "processing",
                    ProcessingJob.id != job.id,
                    ProcessingJob.lease_until > clock,
                ))
                if running >= concurrency:
                    job.status = "queued"
                    job.stage = "queued"
                    job.generation += 1
                    job.next_run_at = clock + 1
                    job.lease_token, job.lease_until, job.updated_at = None, None, now()
                    add_outbox(session, job)
                    return None
            job.status, job.stage, job.lease_token = "processing", "downloading", str(uuid4())
            job.lease_until = clock + self.settings.lease
            job.deadline_at = job.deadline_at or clock + self.settings.timeout
            job.attempts += 1
            job.updated_at = now()
            session.flush()
            session.expunge(job)
            return job

    def set_stage(self, claimed, stage):
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == claimed.id).with_for_update())
            if job is None or job.status != "processing" or job.lease_token != claimed.lease_token:
                return False
            job.stage, job.updated_at = stage, now()
            claimed.stage = stage
            return True

    def attach_original(self, claimed, original_key, size):
        """Файл push-задачи появляется только после скачивания по ссылке."""
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == claimed.id).with_for_update())
            if job is None or job.status != "processing" or job.lease_token != claimed.lease_token:
                return False
            job.original_key, job.size, job.updated_at = original_key, size, now()
            claimed.original_key, claimed.size = original_key, size
            return True

    def complete(self, claimed, document):
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == claimed.id).with_for_update())
            if job is None or job.status != "processing" or job.lease_token != claimed.lease_token:
                return False
            if time.time() >= job.deadline_at or time.time() >= job.lease_until:
                return False
            session.add(document)
            job.status, job.stage, job.failed_stage, job.error, job.updated_at = "succeeded", "completed", None, None, now()
            job.lease_token, job.lease_until = None, None
            return True

    def fail(self, claimed, message, transient):
        clock = time.time()
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == claimed.id).with_for_update())
            if job is None or job.status != "processing" or job.lease_token != claimed.lease_token:
                return
            delay = self.settings.retry_delay * 2 ** (job.attempts - 1)
            if transient and job.attempts < self.settings.max_attempts and clock + delay < job.deadline_at:
                job.status = "queued"
                job.stage = "queued"
                job.generation += 1
                job.next_run_at = clock + delay
                add_outbox(session, job)
            else:
                job.status = "failed"
                job.stage = "failed"
            job.failed_stage = claimed.stage
            job.error, job.updated_at = message, now()
            job.lease_token, job.lease_until = None, None


class OutboxRepository:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    def claim(self, clock=None):
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            event = session.scalar(select(TaskOutbox).where(
                TaskOutbox.published_at.is_(None), TaskOutbox.next_attempt_at <= clock,
                or_(TaskOutbox.lease_until.is_(None), TaskOutbox.lease_until <= clock),
            ).order_by(TaskOutbox.next_attempt_at, TaskOutbox.id).with_for_update(skip_locked=True).limit(1))
            if event is None:
                return None
            event.lease_token, event.lease_until = str(uuid4()), clock + 30
            event.attempts += 1
            session.flush()
            session.expunge(event)
            return event

    def prune(self, clock=None, limit=500):
        """Опубликованные события завершённых задач больше не нужны.

        Без этого task_outbox растёт вечно: по строке на каждое поколение каждой задачи.
        Задачи в очереди и в работе не трогаются — по их событиям работает recover().
        """
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            stale = select(TaskOutbox.id).join(ProcessingJob, ProcessingJob.id == TaskOutbox.job_id).where(
                TaskOutbox.published_at.is_not(None),
                TaskOutbox.published_at <= clock - self.settings.lease,
                ProcessingJob.status.in_(("succeeded", "failed")),
            ).limit(limit)
            result = session.execute(
                delete(TaskOutbox).where(TaskOutbox.id.in_(stale.scalar_subquery())),
                execution_options={"synchronize_session": False},
            )
            return result.rowcount

    def finish(self, claimed, success, clock=None):
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            session.execute(update(TaskOutbox).where(TaskOutbox.id == claimed.id, TaskOutbox.lease_token == claimed.lease_token).values(
                published_at=clock if success else None,
                next_attempt_at=clock if success else clock + min(60, 2 ** min(claimed.attempts, 6)),
                lease_token=None, lease_until=None,
            ))

    def recover(self, clock=None):
        clock = time.time() if clock is None else clock
        with self.sessions.begin() as session:
            jobs = session.scalars(select(ProcessingJob).where(
                ProcessingJob.status.in_(["queued", "processing"]),
                or_(ProcessingJob.lease_until.is_(None), ProcessingJob.lease_until <= clock, ProcessingJob.deadline_at <= clock),
            ).order_by(ProcessingJob.updated_at, ProcessingJob.id).with_for_update(skip_locked=True).limit(100)).all()
            for job in jobs:
                if (job.deadline_at and job.deadline_at <= clock) or job.attempts >= self.settings.max_attempts:
                    job.status, job.error = "failed", "Превышен лимит времени или попыток обработки"
                    job.failed_stage, job.stage = job.stage, "failed"
                    job.lease_token, job.lease_until, job.updated_at = None, None, now()
                    continue
                if job.status == "processing":
                    job.generation += 1
                    job.status, job.next_run_at = "queued", clock
                    job.failed_stage, job.stage = job.stage, "queued"
                    job.lease_token, job.lease_until, job.updated_at = None, None, now()
                event = session.scalar(select(TaskOutbox).where(TaskOutbox.job_id == job.id, TaskOutbox.generation == job.generation))
                if event is None:
                    add_outbox(session, job)
                elif event.published_at and event.published_at < clock - self.settings.lease:
                    event.published_at, event.next_attempt_at = None, max(clock, job.next_run_at)
                # Rotate scanned jobs so a backlog cannot starve recovery of later rows.
                job.updated_at = now()
