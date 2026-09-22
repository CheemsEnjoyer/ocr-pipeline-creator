"""Durable outbox, fenced worker leases, and shared login throttle."""
from alembic import op
import sqlalchemy as sa

revision = "0002_reliable_jobs"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("deadline_at", sa.Float(), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
    ):
        op.add_column("processing_jobs", column)
    op.create_table("task_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.Float(), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.UniqueConstraint("job_id", "generation", name="uq_task_outbox_generation"),
    )
    op.create_index("idx_task_outbox_pending", "task_outbox", ["published_at", "next_attempt_at", "lease_until"])
    guard = op.create_table("login_guard",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("failures", sa.JSON(), nullable=False),
    )
    op.bulk_insert(guard, [{"id": "admin", "failures": []}])


def downgrade():
    op.drop_table("login_guard")
    op.drop_table("task_outbox")
    for name in ("lease_until", "lease_token", "deadline_at", "next_run_at", "attempts", "generation"):
        op.drop_column("processing_jobs", name)
