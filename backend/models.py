from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, Float, Index, Integer, String, Text, UniqueConstraint, CheckConstraint, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    RESPONSE_SENDING_ERROR = "response_sending_error"


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_type_id: Mapped[int] = mapped_column(ForeignKey("document_types.id"))
    callback_url: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, create_constraint=True, name="task_status"),
        default=TaskStatus.PENDING,
    )
    task_update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    task_completion_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_type: Mapped[DocumentType] = relationship()
    file: Mapped["File | None"] = relationship(back_populates="task", cascade="all, delete-orphan", uselist=False)


class File(Base):
    __tablename__ = "task_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    s3_link: Mapped[str] = mapped_column(Text)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    task: Mapped[Task] = relationship(back_populates="file")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("idx_documents_created_at", "created_at", "id"), Index("idx_documents_api_key", "api_key_id", "created_at", "id"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    pipeline_name: Mapped[str] = mapped_column(Text)
    original_key: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    result_schema: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    fields: Mapped[dict] = mapped_column(JSON_TYPE)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    # Источник обработки: по api_key_id ключ интеграции видит только свои документы. У старых записей пусто.
    pipeline_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("integration_clients.id"), nullable=True, index=True)



class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("idx_processing_jobs_api_key", "api_key_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    original_key: Mapped[str] = mapped_column(Text)
    pipeline: Mapped[dict] = mapped_column(JSON_TYPE)
    pipeline_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("integration_clients.id"), nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_run_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    deadline_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        UniqueConstraint("job_id", "generation", name="uq_task_outbox_generation"),
        Index("idx_task_outbox_pending", "published_at", "next_attempt_at", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class LoginGuard(Base):
    __tablename__ = "login_guard"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    failures: Mapped[list] = mapped_column(JSON_TYPE, default=list)


class SavedPipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    config: Mapped[dict] = mapped_column(JSON_TYPE)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    deleted: Mapped[int] = mapped_column(Integer, default=0)



class IntegrationClient(Base):
    __tablename__ = "integration_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    pipeline_ids: Mapped[list] = mapped_column(JSON_TYPE)
    created_at: Mapped[str] = mapped_column(String(32))


class ProcessingCapacity(Base):
    __tablename__ = "processing_capacity"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)


class SyncProcessingSlot(Base):
    __tablename__ = "sync_processing_slots"
    __table_args__ = (
        Index("idx_sync_processing_slots_expires", "expires_at"),
        Index("idx_sync_processing_slots_client", "client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("integration_clients.id"), nullable=True)
    expires_at: Mapped[float] = mapped_column(Float)


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[str] = mapped_column(ForeignKey("integration_clients.id"), index=True)
    permissions: Mapped[list] = mapped_column(JSON_TYPE)
    created_at: Mapped[str] = mapped_column(String(32))
    revoked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"), CheckConstraint("status IN ('invited', 'active', 'deleted')", name="ck_users_status"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    login: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    invite_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    invite_expires: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_bootstrap: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(String(32))


class OIDCFlow(Base):
    __tablename__ = "oidc_flows"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class OIDCSession(Base):
    __tablename__ = "oidc_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, index=True)
    payload: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


