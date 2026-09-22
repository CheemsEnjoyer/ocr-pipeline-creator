from sqlalchemy import JSON, Float, Index, Integer, String, Text, UniqueConstraint, CheckConstraint, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

# Состояния фоновой задачи. Значения ограничены в базе: опечатка в stage не должна
# записаться молча и застрять в истории.
JOB_STATUSES = ("queued", "processing", "succeeded", "failed")
JOB_STAGES = ("queued", "downloading", "recognition", "extraction", "validation", "saving", "completed", "failed")
# Доставка результата во внешнюю систему. Живёт отдельно от статуса задачи:
# документ может быть распознан, а callback не доставлен, и наоборот.
CALLBACK_STATUSES = ("pending", "sent", "failed")


def one_of(column, values, nullable=False):
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})" + (f" OR {column} IS NULL" if nullable else "")


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Результат обработки.

    У фоновых задач id совпадает с id строки в processing_jobs: связь один-к-одному
    через общий ключ (см. ProcessingService.execute и GET /jobs/{id}).
    У синхронной обработки задачи нет, и id свой.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_created_at", "created_at", "id"),
        Index("idx_documents_pipeline", "pipeline_id", "created_at", "id"),
    )

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
    # Пайплайн удаляется мягко, а его id неизменяем, поэтому ссылка не протухает.
    pipeline_id: Mapped[str | None] = mapped_column(String(80), ForeignKey("pipelines.id"), nullable=True)
    # Аудит: каким ключом создано. Доступ разграничивает client_id — по api_key_id не фильтруют.
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("integration_clients.id"), nullable=True, index=True)


class ProcessingJob(Base):
    """Фоновая задача. pipeline хранит снимок конфигурации на момент постановки."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(one_of("status", JOB_STATUSES), name="ck_processing_jobs_status"),
        CheckConstraint(one_of("stage", JOB_STAGES), name="ck_processing_jobs_stage"),
        CheckConstraint(one_of("failed_stage", JOB_STAGES, nullable=True), name="ck_processing_jobs_failed_stage"),
        # Диспетчер каждую секунду ищет задачи для восстановления в этом порядке.
        Index("idx_processing_jobs_recover", "status", "updated_at", "id"),
        # claim() считает активные задачи пайплайна перед выдачей аренды.
        Index("idx_processing_jobs_pipeline", "pipeline_id", "status"),
        # Код задачи назначает вызывающая система, поэтому он уникален внутри клиента,
        # а не глобально: две учётные системы вправе прислать один и тот же код.
        UniqueConstraint("client_id", "task_code", name="uq_processing_jobs_task_code"),
        CheckConstraint(one_of("callback_status", CALLBACK_STATUSES, nullable=True), name="ck_processing_jobs_callback_status"),
        # Диспетчер каждую секунду ищет задачи, чей результат пора отправить.
        Index("idx_processing_jobs_callback", "callback_status", "callback_next_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued")
    failed_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    # Пусто до скачивания: push-задача приходит ссылкой, файл забирает воркер.
    original_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline: Mapped[dict] = mapped_column(JSON_TYPE)
    pipeline_id: Mapped[str | None] = mapped_column(String(80), ForeignKey("pipelines.id"), nullable=True)
    # Аудит: каким ключом поставлена. Доступ разграничивает client_id.
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
    # Push-модель: код задачи внешней системы и адрес, куда вернуть результат.
    task_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    callback_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    callback_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    callback_next_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    callback_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        UniqueConstraint("job_id", "generation", name="uq_task_outbox_generation"),
        Index("idx_task_outbox_pending", "published_at", "next_attempt_at", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"))
    generation: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class LoginGuard(Base):
    """Единственная строка "admin": окно неудачных входов и общий мьютекс проверки пароля."""

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
    """Строка-мьютекс, а не данные.

    Единственная строка "sync" блокируется через SELECT ... FOR UPDATE и сериализует
    подсчёт синхронных слотов между процессами API. Работает на любом диалекте,
    в отличие от advisory-локов PostgreSQL.
    """

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


