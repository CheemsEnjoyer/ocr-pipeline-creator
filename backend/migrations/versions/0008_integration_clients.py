"""Separate integration ownership from revocable credentials."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_integration_clients"
down_revision = "0007_result_schema"
branch_labels = None
depends_on = None
json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade():
    clients = op.create_table("integration_clients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("pipeline_ids", json_type, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False))
    op.add_column("api_keys", sa.Column("client_id", sa.String(36), nullable=True))
    op.add_column("api_keys", sa.Column("permissions", json_type, nullable=True))
    keys = sa.table("api_keys", sa.column("id", sa.String), sa.column("name", sa.String),
        sa.column("pipeline_ids", json_type), sa.column("created_at", sa.String),
        sa.column("client_id", sa.String), sa.column("permissions", json_type))
    connection = op.get_bind()
    # Includes revoked keys: their documents must keep a recoverable owner.
    for key in connection.execute(sa.select(keys)).mappings().all():
        connection.execute(clients.insert().values(id=key["id"], name=key["name"], pipeline_ids=key["pipeline_ids"], created_at=key["created_at"]))
        connection.execute(keys.update().where(keys.c.id == key["id"]).values(client_id=key["id"], permissions=["run", "results", "history"]))
    for table in ("documents", "processing_jobs"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("client_id", sa.String(36), nullable=True))
            batch.create_foreign_key(f"fk_{table}_client", "integration_clients", ["client_id"], ["id"])
            batch.create_index(f"ix_{table}_client_id", ["client_id"])
        rows = sa.table(table, sa.column("client_id", sa.String), sa.column("api_key_id", sa.String))
        connection.execute(rows.update().values(client_id=sa.select(keys.c.client_id).where(keys.c.id == rows.c.api_key_id).scalar_subquery()))
    with op.batch_alter_table("api_keys") as batch:
        batch.alter_column("client_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("permissions", existing_type=json_type, nullable=False)
        batch.create_foreign_key("fk_api_keys_client", "integration_clients", ["client_id"], ["id"])
        batch.create_index("ix_api_keys_client_id", ["client_id"])
        batch.drop_column("pipeline_ids")


def downgrade():
    # Old key isolation cannot represent shared client ownership safely.
    raise RuntimeError("Client ownership migration requires a database backup to roll back")
