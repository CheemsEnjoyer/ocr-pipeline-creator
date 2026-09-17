"""Persist Celery priority for background jobs and outbox retries."""
from alembic import op
import sqlalchemy as sa

revision = "0009_pipeline_priority"
down_revision = "0008_integration_clients"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("task_outbox", sa.Column("priority", sa.Integer(), nullable=False, server_default="5"))


def downgrade():
    op.drop_column("task_outbox", "priority")
    op.drop_column("processing_jobs", "priority")
