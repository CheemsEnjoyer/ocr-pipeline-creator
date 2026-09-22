import asyncio
import logging
import time
from uuid import uuid4

import anyio.to_thread
import httpx
from billiard.exceptions import SoftTimeLimitExceeded
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import OperationalError

from ..core.config import JobSettings
from ..core.errors import DomainError, ProcessingTimeout
from ..db.domain.models import Document, ProcessingJob
from ..db.infra.repositories import DocumentRepository, JobRepository, SyncCapacityRepository, now
from ..schema.pipeline import Pipeline, result_schema
from ..core.security import redact, safe_url
from .recognition import extract, recognize
from .validation import result_fields


def build_document(document_id, original_key, filename, mime, size, parsed, text, result, pipeline_id, api_key_id, client_id=None):
    timestamp = now()
    return Document(
        id=document_id, filename=filename, mime_type=mime, size=size, pipeline_name=parsed.name,
        original_key=original_key, text=text, result=result,
        fields={} if parsed.extraction and not parsed.extraction.use_fields else result_fields(result),
        result_schema=result_schema(parsed),
        created_at=timestamp, updated_at=timestamp, revision=0, pipeline_id=pipeline_id, api_key_id=api_key_id, client_id=client_id,
    )


async def process_pipeline(client, parsed, content, filename, mime, timeout, on_stage=None):
    async def process():
        stage = "recognition"
        started = time.monotonic()
        try:
            if on_stage:
                on_stage(stage)
            text = await recognize(client, parsed, content, filename, mime)
            stage = "extraction"
            started = time.monotonic()
            if parsed.extraction:
                if on_stage:
                    on_stage(stage)
                result = await extract(client, parsed.extraction, text, (lambda: on_stage("validation")) if on_stage else None)
            else:
                result = text
            return text, result
        except httpx.TimeoutException as error:
            request = getattr(error, "_request", None)
            logging.getLogger("ocr.worker").error(
                "Upstream timeout: stage=%s, error=%s, url=%s, elapsed=%.1fs",
                stage, type(error).__name__, safe_url(request.url if request else None),
                time.monotonic() - started,
            )
            raise
    return await asyncio.wait_for(process(), timeout=timeout)


def transient_error(error):
    if isinstance(error, (httpx.TransportError, TimeoutError, SoftTimeLimitExceeded, OperationalError)):
        return True
    if isinstance(error, DomainError):
        return error.transient
    cause = error.__cause__ or error
    if isinstance(cause, ClientError):
        code = cause.response.get("Error", {}).get("Code")
        status = cause.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return code in {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "Throttling"} or status in {429, 500, 502, 503, 504}
    return isinstance(cause, BotoCoreError) and type(cause).__name__ in {"ConnectTimeoutError", "ReadTimeoutError", "EndpointConnectionError", "ConnectionClosedError"}


def error_message(error):
    if isinstance(error, DomainError):
        return redact(error.message)
    if isinstance(error, (TimeoutError, SoftTimeLimitExceeded)):
        return "Превышено время одной попытки обработки"
    if isinstance(error, httpx.TimeoutException):
        request = getattr(error, "_request", None)
        return redact(f"Сервис OCR или LiteLLM не ответил вовремя: {safe_url(request.url if request else None)}")
    return "Не удалось обработать документ. Проверьте доступность S3, OCR и LiteLLM."


class ProcessingService:
    def __init__(self, sessions, originals, settings=None):
        self.originals = originals
        self.settings = settings or JobSettings.from_env()
        self.documents = DocumentRepository(sessions)
        self.jobs = JobRepository(sessions, self.settings)
        self.sync_capacity = SyncCapacityRepository(sessions, self.settings)

    def cleanup(self, key):
        try:
            self.originals.delete(key)
        except Exception:
            import logging
            logging.getLogger("ocr").error("Не удалось очистить исходник после ошибки базы")

    async def run(self, client, content, filename, mime, parsed, pipeline_id=None, api_key_id=None, client_id=None):
        try:
            text, result = await process_pipeline(client, parsed, content, filename, mime, self.settings.timeout)
        except TimeoutError as error:
            raise ProcessingTimeout("Превышено время обработки документа") from error
        document_id = str(uuid4())
        original_key = await anyio.to_thread.run_sync(self.originals.put, document_id, content, mime)
        document = build_document(document_id, original_key, filename, mime, len(content), parsed, text, result, pipeline_id, api_key_id, client_id)
        try:
            await anyio.to_thread.run_sync(self.documents.save, document)
        except Exception:
            await anyio.to_thread.run_sync(self.cleanup, original_key)
            raise
        return {"file": filename, "text": text, "result": result, "documentId": document_id}

    def submit(self, content, filename, mime, parsed, pipeline_id=None, api_key_id=None, client_id=None):
        job_id = str(uuid4())
        original_key = self.originals.put(job_id, content, mime)
        timestamp = now()
        job = ProcessingJob(
            id=job_id, status="queued", filename=filename, mime_type=mime, size=len(content), original_key=original_key,
            pipeline=parsed.model_dump(mode="json"), pipeline_id=pipeline_id, api_key_id=api_key_id, client_id=client_id,
            priority=parsed.priority, created_at=timestamp, updated_at=timestamp, generation=0, attempts=0, next_run_at=0,
        )
        try:
            self.jobs.create(job)
        except Exception:
            self.cleanup(original_key)
            raise
        return job_id

    def execute(self, job_id, generation=None, transport=None):
        claimed = self.jobs.claim(job_id, generation)
        if claimed is None:
            return
        try:
            path = self.originals.download(claimed.original_key)
            try:
                content = path.read_bytes()
            finally:
                path.unlink(missing_ok=True)
            parsed = Pipeline.model_validate(claimed.pipeline)

            async def process():
                remaining = min(self.settings.soft_limit, claimed.deadline_at - time.time())
                if remaining <= 0:
                    raise TimeoutError()
                async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), transport=transport) as client:
                    return await process_pipeline(
                        client, parsed, content, claimed.filename, claimed.mime_type, remaining,
                        on_stage=lambda stage: self.jobs.set_stage(claimed, stage),
                    )

            text, result = asyncio.run(process())
            self.jobs.set_stage(claimed, "saving")
            document = build_document(claimed.id, claimed.original_key, claimed.filename, claimed.mime_type, claimed.size, parsed, text, result, claimed.pipeline_id, claimed.api_key_id, claimed.client_id)
            self.jobs.complete(claimed, document)
        except Exception as error:
            import logging
            logging.getLogger("ocr.worker").error("Ошибка задачи %s: %s", job_id, type(error).__name__)
            self.jobs.fail(claimed, error_message(error), transient_error(error))
