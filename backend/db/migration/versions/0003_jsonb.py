"""Convert PostgreSQL JSON columns to JSONB, preserving their values."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_jsonb"
down_revision = "0002_reliable_jobs"
branch_labels = None
depends_on = None

COLUMNS = (
    ("documents", "fields"),
    ("processing_jobs", "pipeline"),
    ("pipelines", "config"),
    ("api_keys", "pipeline_ids"),
    ("login_guard", "failures"),
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=sa.JSON(), type_=JSONB(), existing_nullable=False, postgresql_using=f"{column}::jsonb")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=JSONB(), type_=sa.JSON(), existing_nullable=False, postgresql_using=f"{column}::json")
