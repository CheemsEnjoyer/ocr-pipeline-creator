"""MIME type of the task file, supplied by the caller alongside the link."""
from alembic import op
import sqlalchemy as sa

revision = "0013_task_content_type"
down_revision = "0012_model_integrity"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable без backfill: у ранее созданных задач MIME взять неоткуда.
    op.add_column("task_files", sa.Column("content_type", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("task_files", "content_type")
