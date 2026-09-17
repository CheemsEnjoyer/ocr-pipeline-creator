"""Preserve the public result contract at processing time."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_result_schema"
down_revision = "0006_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("result_schema", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True))


def downgrade():
    op.drop_column("documents", "result_schema")
