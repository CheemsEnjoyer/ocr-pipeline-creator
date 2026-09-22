"""Declare the relationships the code already relies on, and drop what nothing reads."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_model_integrity"
down_revision = "0011_job_stages"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
STATUSES = ("queued", "processing", "succeeded", "failed")
STAGES = ("queued", "downloading", "recognition", "extraction", "validation", "saving", "completed", "failed")


def quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def pipelines_table():
    return sa.table(
        "pipelines",
        sa.column("id", sa.String),
        sa.column("config", JSON_TYPE),
        sa.column("created_at", sa.String),
        sa.column("updated_at", sa.String),
        sa.column("deleted", sa.Integer),
    )


def restore_missing_pipelines(connection):
    """Документы и задачи ссылаются на пайплайн строкой, и ссылка может быть висячей.

    Такие записи остались от прежних версий, где пайплайн удалялся physически. Вместо
    обнуления ссылки (и потери фильтра в истории) недостающий пайплайн восстанавливается
    как удалённый: история продолжает работать, а внешний ключ становится возможным.
    """
    pipelines = pipelines_table()
    documents = sa.table("documents", sa.column("pipeline_id", sa.String), sa.column("pipeline_name", sa.String))
    jobs = sa.table("processing_jobs", sa.column("pipeline_id", sa.String))

    known = {row[0] for row in connection.execute(sa.select(pipelines.c.id))}
    missing = {}
    rows = connection.execute(sa.select(documents.c.pipeline_id, documents.c.pipeline_name).where(documents.c.pipeline_id.is_not(None)).distinct())
    for pipeline_id, name in rows:
        if pipeline_id not in known:
            missing.setdefault(pipeline_id, name or pipeline_id)
    rows = connection.execute(sa.select(jobs.c.pipeline_id).where(jobs.c.pipeline_id.is_not(None)).distinct())
    for (pipeline_id,) in rows:
        if pipeline_id not in known:
            missing.setdefault(pipeline_id, pipeline_id)
    if not missing:
        return
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    op.bulk_insert(pipelines, [
        {"id": pipeline_id, "config": {"name": name, "source": "document"},
         "created_at": timestamp, "updated_at": timestamp, "deleted": 1}
        for pipeline_id, name in sorted(missing.items())
    ])


def upgrade():
    connection = op.get_bind()

    # Доступ разграничивает client_id: по api_key_id не фильтруют, а индексы по нему
    # перестраиваются на каждой вставке. Сама колонка остаётся как аудит.
    op.drop_index("idx_documents_api_key", table_name="documents")
    op.drop_index("idx_processing_jobs_api_key", table_name="processing_jobs")

    restore_missing_pipelines(connection)
    outbox = sa.table("task_outbox", sa.column("job_id", sa.String))
    jobs = sa.table("processing_jobs", sa.column("id", sa.String), sa.column("status", sa.String),
                    sa.column("stage", sa.String), sa.column("failed_stage", sa.String))
    connection.execute(outbox.delete().where(outbox.c.job_id.not_in(sa.select(jobs.c.id))))

    # Значения вне словаря состояний могли попасть только из сломанной записи: приводим
    # их к безопасным, иначе ограничение не даст применить миграцию.
    connection.execute(jobs.update().where(jobs.c.status.not_in(STATUSES)).values(status="failed"))
    connection.execute(jobs.update().where(jobs.c.stage.not_in(STAGES)).values(stage="queued"))
    connection.execute(jobs.update().where(jobs.c.failed_stage.is_not(None)).where(jobs.c.failed_stage.not_in(STAGES)).values(failed_stage=None))

    with op.batch_alter_table("documents") as batch:
        batch.create_foreign_key("fk_documents_pipeline", "pipelines", ["pipeline_id"], ["id"])
    with op.batch_alter_table("processing_jobs") as batch:
        batch.create_foreign_key("fk_processing_jobs_pipeline", "pipelines", ["pipeline_id"], ["id"])
        batch.create_check_constraint("ck_processing_jobs_status", f"status IN ({quoted(STATUSES)})")
        batch.create_check_constraint("ck_processing_jobs_stage", f"stage IN ({quoted(STAGES)})")
        batch.create_check_constraint("ck_processing_jobs_failed_stage", f"failed_stage IN ({quoted(STAGES)}) OR failed_stage IS NULL")
    with op.batch_alter_table("task_outbox") as batch:
        batch.create_foreign_key("fk_task_outbox_job", "processing_jobs", ["job_id"], ["id"], ondelete="CASCADE")

    # Индексы под запросы, которые действительно выполняются: фильтр истории по пайплайну,
    # восстановление задач диспетчером и подсчёт активных задач пайплайна в claim().
    op.create_index("idx_documents_pipeline", "documents", ["pipeline_id", "created_at", "id"])
    op.create_index("idx_processing_jobs_recover", "processing_jobs", ["status", "updated_at", "id"])
    op.create_index("idx_processing_jobs_pipeline", "processing_jobs", ["pipeline_id", "status"])


def downgrade():
    # Восстановленные пайплайны остаются: отличить их от настоящих удалённых уже нельзя.
    op.drop_index("idx_processing_jobs_pipeline", table_name="processing_jobs")
    op.drop_index("idx_processing_jobs_recover", table_name="processing_jobs")
    op.drop_index("idx_documents_pipeline", table_name="documents")
    with op.batch_alter_table("task_outbox") as batch:
        batch.drop_constraint("fk_task_outbox_job", type_="foreignkey")
    with op.batch_alter_table("processing_jobs") as batch:
        batch.drop_constraint("ck_processing_jobs_failed_stage", type_="check")
        batch.drop_constraint("ck_processing_jobs_stage", type_="check")
        batch.drop_constraint("ck_processing_jobs_status", type_="check")
        batch.drop_constraint("fk_processing_jobs_pipeline", type_="foreignkey")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("fk_documents_pipeline", type_="foreignkey")
    op.create_index("idx_processing_jobs_api_key", "processing_jobs", ["api_key_id", "created_at"])
    op.create_index("idx_documents_api_key", "documents", ["api_key_id", "created_at", "id"])
