"""Persist the current and failed processing stages for background jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0011_job_stages"
down_revision = "0010_sync_capacity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_jobs", sa.Column("stage", sa.String(length=24), nullable=False, server_default="queued"))
    op.add_column("processing_jobs", sa.Column("failed_stage", sa.String(length=24), nullable=True))
    op.execute("""
        UPDATE processing_jobs
        SET stage = CASE status
            WHEN 'succeeded' THEN 'completed'
            WHEN 'failed' THEN 'failed'
            WHEN 'processing' THEN 'recognition'
            ELSE 'queued'
        END
    """)


def downgrade():
    op.drop_column("processing_jobs", "failed_stage")
    op.drop_column("processing_jobs", "stage")
