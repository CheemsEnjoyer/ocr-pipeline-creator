"""Add distributed capacity slots for synchronous processing."""
from alembic import op
import sqlalchemy as sa

revision = "0010_sync_capacity"
down_revision = "0009_pipeline_priority"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("processing_capacity", sa.Column("id", sa.String(length=32), primary_key=True))
    op.bulk_insert(sa.table("processing_capacity", sa.column("id", sa.String(length=32))), [{"id": "sync"}])
    op.create_table(
        "sync_processing_slots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("client_id", sa.String(length=36), sa.ForeignKey("integration_clients.id"), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_index("idx_sync_processing_slots_expires", "sync_processing_slots", ["expires_at"])
    op.create_index("idx_sync_processing_slots_client", "sync_processing_slots", ["client_id"])


def downgrade():
    op.drop_index("idx_sync_processing_slots_client", table_name="sync_processing_slots")
    op.drop_index("idx_sync_processing_slots_expires", table_name="sync_processing_slots")
    op.drop_table("sync_processing_slots")
    op.drop_table("processing_capacity")
