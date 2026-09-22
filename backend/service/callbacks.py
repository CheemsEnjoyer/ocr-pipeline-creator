"""Доставка результата во внешнюю учётную систему.

Задача и её callback живут порознь: документ может быть распознан, а ответ не
доставлен. Поэтому попытки отправки считаются отдельно от попыток обработки —
повтор доставки не должен заново гонять OCR.
"""
import logging
import time

import httpx
from sqlalchemy import or_, select

from ..core.security import UnsafeUrl, check_external_url, redact, safe_url
from ..db.domain.models import Document, ProcessingJob
from ..db.infra.repositories import now
from ..schema.api import public_result

logger = logging.getLogger("ocr.callback")
MAX_ATTEMPTS = 6
LEASE_SECONDS = 120


def build_payload(session, job):
    body = {"task_code": job.task_code, "task_id": job.id, "status": job.status}
    if job.status == "failed":
        return {**body, "error": job.error, "failed_stage": job.failed_stage}
    document = session.get(Document, job.id)
    if document is None:
        return body
    return {**body, "document_id": document.id, "file": document.filename,
            "text": document.text, "result": public_result(document)}


def claim(sessions, clock=None):
    """Берёт одну готовую задачу к отправке и сразу продлевает её срок.

    Аренда через callback_next_at: пока идёт запрос наружу, соседний проход
    диспетчера ту же задачу не возьмёт, а упавший процесс освободит её по времени.
    """
    clock = time.time() if clock is None else clock
    with sessions.begin() as session:
        job = session.scalar(select(ProcessingJob).where(
            ProcessingJob.callback_status == "pending",
            ProcessingJob.callback_url.is_not(None),
            ProcessingJob.status.in_(("succeeded", "failed")),
            ProcessingJob.callback_next_at <= clock,
        ).order_by(ProcessingJob.callback_next_at, ProcessingJob.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        job.callback_attempts += 1
        job.callback_next_at = clock + LEASE_SECONDS
        job.updated_at = now()
        return {"id": job.id, "url": job.callback_url, "attempts": job.callback_attempts,
                "payload": build_payload(session, job)}


def finish(sessions, claimed, error=None, clock=None):
    clock = time.time() if clock is None else clock
    with sessions.begin() as session:
        job = session.get(ProcessingJob, claimed["id"], with_for_update=True)
        if job is None or job.callback_status != "pending":
            return
        if error is None:
            job.callback_status, job.callback_error = "sent", None
        elif claimed["attempts"] >= MAX_ATTEMPTS:
            # Попытки исчерпаны: результат остаётся в истории, его можно забрать опросом.
            job.callback_status, job.callback_error = "failed", redact(error)
        else:
            job.callback_error = redact(error)
            job.callback_next_at = clock + min(600, 10 * 2 ** (claimed["attempts"] - 1))
        job.updated_at = now()


def send(claimed, transport=None):
    check_external_url(claimed["url"], "Адрес callback")
    with httpx.Client(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
        response = client.post(claimed["url"], json=claimed["payload"])
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request, response=response)


def deliver_once(sessions, sender=send, limit=20):
    delivered = 0
    for _ in range(limit):
        claimed = claim(sessions)
        if claimed is None:
            break
        try:
            sender(claimed)
        except (httpx.HTTPError, UnsafeUrl, OSError) as error:
            logger.warning("Callback задачи %s не доставлен (%s): %s", claimed["id"],
                           safe_url(claimed["url"]), type(error).__name__)
            finish(sessions, claimed, error=f"{type(error).__name__}: {error}")
        else:
            finish(sessions, claimed)
            delivered += 1
    return delivered
