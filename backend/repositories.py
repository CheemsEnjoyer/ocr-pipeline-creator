import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update

from .models import Document, ProcessingJob, TaskOutbox


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def add_outbox(session, job):
    session.add(TaskOutbox(id=str(uuid4()), job_id=job.id, generation=job.generation or 0, next_attempt_at=job.next_run_at or 0))


class DocumentRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    def save(self, document):
        with self.sessions.begin() as session:
            session.add(document)


class JobRepository:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    def create(self, job):
        with self.sessions.begin() as session:
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
                job.lease_token, job.lease_until = None, None
                return None
            job.status, job.lease_token = "processing", str(uuid4())
            job.lease_until = clock + self.settings.lease
            job.deadline_at = job.deadline_at or clock + self.settings.timeout
            job.attempts += 1
            job.updated_at = now()
            session.flush()
            session.expunge(job)
            return job

    def complete(self, claimed, document):
        with self.sessions.begin() as session:
            job = session.scalar(select(ProcessingJob).where(ProcessingJob.id == claimed.id).with_for_update())
            if job is None or job.status != "processing" or job.lease_token != claimed.lease_token:
                return False
            if time.time() >= job.deadline_at or time.time() >= job.lease_until:
                return False
            session.add(document)
            job.status, job.error, job.updated_at = "succeeded", None, now()
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
                job.generation += 1
                job.next_run_at = clock + delay
                add_outbox(session, job)
            else:
                job.status = "failed"
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
                    job.lease_token, job.lease_until, job.updated_at = None, None, now()
                    continue
                if job.status == "processing":
                    job.generation += 1
                    job.status, job.next_run_at = "queued", clock
                    job.lease_token, job.lease_until, job.updated_at = None, None, now()
                event = session.scalar(select(TaskOutbox).where(TaskOutbox.job_id == job.id, TaskOutbox.generation == job.generation))
                if event is None:
                    add_outbox(session, job)
                elif event.published_at and event.published_at < clock - self.settings.lease:
                    event.published_at, event.next_attempt_at = None, max(clock, job.next_run_at)
                # Rotate scanned jobs so a backlog cannot starve recovery of later rows.
                job.updated_at = now()
