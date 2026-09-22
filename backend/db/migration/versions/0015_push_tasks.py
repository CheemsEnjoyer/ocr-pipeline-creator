"""Push-модель: задача приходит ссылкой, результат уходит на callback.

Островок TaskService (tasks, task_files, document_types) снимается: очередь,
ретраи и стадии уже есть в processing_jobs, вторая машина состояний не нужна.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_push_tasks"
down_revision = "0014_remove_public_descriptions"
branch_labels = None
depends_on = None

CALLBACK_STATUSES = ("pending", "sent", "failed")


def quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def upgrade():
    with op.batch_alter_table("processing_jobs") as batch:
        # Ссылка вместо файла: original_key появляется только после скачивания.
        batch.alter_column("original_key", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("task_code", sa.String(80), nullable=True))
        batch.add_column(sa.Column("callback_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("callback_status", sa.String(16), nullable=True))
        batch.add_column(sa.Column("callback_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("callback_next_at", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("callback_error", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_processing_jobs_task_code", ["client_id", "task_code"])
        batch.create_check_constraint("ck_processing_jobs_callback_status",
                                      f"callback_status IN ({quoted(CALLBACK_STATUSES)}) OR callback_status IS NULL")
    op.create_index("idx_processing_jobs_callback", "processing_jobs", ["callback_status", "callback_next_at"])

    op.drop_table("task_files")
    op.drop_table("tasks")
    op.drop_table("document_types")


def downgrade():
    document_types = op.create_table(
        "document_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
    )
    op.bulk_insert(document_types, [{"name": "generic"}])
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("document_type_id", sa.Integer(), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "PROCESSING", "DONE", "ERROR", "RESPONSE_SENDING_ERROR",
                                    native_enum=False, create_constraint=True, name="task_status"), nullable=False),
        sa.Column("task_update_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_completion_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "task_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("s3_link", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(80), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True),
    )

    op.drop_index("idx_processing_jobs_callback", table_name="processing_jobs")
    # Задачи-ссылки без скачанного файла откатить некуда: без original_key колонка
    # снова станет NOT NULL, поэтому такие строки удаляются вместе с их событиями.
    connection = op.get_bind()
    jobs = sa.table("processing_jobs", sa.column("id", sa.String), sa.column("original_key", sa.Text))
    outbox = sa.table("task_outbox", sa.column("job_id", sa.String))
    orphans = sa.select(jobs.c.id).where(jobs.c.original_key.is_(None))
    connection.execute(outbox.delete().where(outbox.c.job_id.in_(orphans)))
    connection.execute(jobs.delete().where(jobs.c.original_key.is_(None)))
    with op.batch_alter_table("processing_jobs") as batch:
        batch.drop_constraint("ck_processing_jobs_callback_status", type_="check")
        batch.drop_constraint("uq_processing_jobs_task_code", type_="unique")
        batch.drop_column("callback_error")
        batch.drop_column("callback_next_at")
        batch.drop_column("callback_attempts")
        batch.drop_column("callback_status")
        batch.drop_column("callback_url")
        batch.drop_column("task_code")
        batch.drop_column("source_url")
        batch.alter_column("original_key", existing_type=sa.Text(), nullable=False)
