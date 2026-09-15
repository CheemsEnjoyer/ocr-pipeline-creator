"""Encrypted OIDC flows and server-side sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0005_keycloak"
down_revision = "0004_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("oidc_flows", sa.Column("id", sa.String(64), primary_key=True), sa.Column("payload", sa.Text(), nullable=False), sa.Column("expires_at", sa.Float(), nullable=False))
    op.create_table("oidc_sessions", sa.Column("id", sa.String(64), primary_key=True), sa.Column("subject", sa.Text(), nullable=False), sa.Column("payload", sa.Text(), nullable=False), sa.Column("expires_at", sa.Float(), nullable=False))
    op.create_index("ix_oidc_sessions_subject", "oidc_sessions", ["subject"])


def downgrade():
    op.drop_table("oidc_sessions")
    op.drop_table("oidc_flows")
