"""Persistence for Tasks; processing and callback delivery are separate concerns."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db.domain.models import DocumentType, File, Task, TaskStatus
from ..schema.api import InitTaskRequestDTO


FINISH_STATUS = frozenset({TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.RESPONSE_SENDING_ERROR})
# Explicit legacy numeric codes: changing enum order must not change the API.
STATUS_CODES = {0: TaskStatus.PENDING, 1: TaskStatus.PROCESSING, 2: TaskStatus.DONE,
                3: TaskStatus.ERROR, 4: TaskStatus.RESPONSE_SENDING_ERROR}


def normalize_status(status: TaskStatus | str | int) -> TaskStatus:
    if isinstance(status, TaskStatus):
        return status
    if type(status) is int:
        try:
            return STATUS_CODES[status]
        except KeyError as exc:
            raise ValueError(f"Invalid status code {status}; expected one of {list(STATUS_CODES)}") from exc
    if isinstance(status, str):
        try:
            return TaskStatus[status.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid status {status!r}; expected one of {list(TaskStatus.__members__)}") from exc
    raise TypeError("status must be TaskStatus, str or int")


class TaskService:
    """Write methods commit the supplied session and roll back on failure.

    Use a dedicated session. Database and validation errors propagate to the caller;
    False/None indicate a missing task only.
    """

    @staticmethod
    def create_task(request_data: InitTaskRequestDTO, db: Session) -> bool:
        try:
            doc_type = db.scalar(select(DocumentType).where(DocumentType.name == request_data.document_type))
            if doc_type is None:
                raise ValueError(f"DocumentType {request_data.document_type!r} not found")
            task = Task(id=request_data.task_code, document_type_id=doc_type.id,
                        callback_url=request_data.callback_url, status=TaskStatus.PENDING)
            task.file = File(s3_link=request_data.document_link, content_type=request_data.content_type)
            db.add(task)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_task_status(task_code: str, status: TaskStatus | str | int, db: Session) -> bool:
        try:
            new_status = normalize_status(status)
            task = db.scalar(select(Task).where(Task.id == task_code).with_for_update())
            if task is None:
                return False
            timestamp = datetime.now(timezone.utc)
            # Repeated final updates preserve completion time; reopening clears it.
            if new_status in FINISH_STATUS:
                if task.task_completion_time is None:
                    task.task_completion_time = timestamp
            else:
                task.task_completion_time = None
            task.status = new_status
            task.task_update_time = timestamp
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_status_by_code(task_code: str, db: Session) -> TaskStatus | None:
        return db.scalar(select(Task.status).where(Task.id == task_code))

    @staticmethod
    def is_task_existing(task_code: str, db: Session) -> bool:
        return db.scalar(select(Task.id).where(Task.id == task_code)) is not None

    @staticmethod
    def get_task_data(task_code: str, db: Session) -> tuple[Task, DocumentType, str, File] | None:
        task = db.scalar(select(Task).options(joinedload(Task.document_type), joinedload(Task.file))
                         .where(Task.id == task_code))
        if task is None or task.document_type is None or task.file is None or task.callback_url is None:
            return None
        return task, task.document_type, task.callback_url, task.file
