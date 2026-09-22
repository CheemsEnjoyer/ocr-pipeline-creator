"""Task persistence and default document type."""
from alembic import op
import sqlalchemy as sa

revision = "0006_tasks"
down_revision = "0005_keycloak"
branch_labels = None
depends_on = None


def upgrade():
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
        sa.Column("task_id", sa.String(80), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True),
    )


def downgrade():
    op.drop_table("task_files")
    op.drop_table("tasks")
    op.drop_table("document_types")
