"""User accounts and invitation-based onboarding."""
from alembic import op
import sqlalchemy as sa

revision = "0004_users"
down_revision = "0003_jsonb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("login", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("invite_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("invite_expires", sa.Float(), nullable=True),
        sa.Column("is_bootstrap", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('invited', 'active', 'deleted')", name="ck_users_status"),
    )
    with op.batch_alter_table("admin_sessions") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_admin_sessions_user", "users", ["user_id"], ["id"], ondelete="CASCADE")


def downgrade():
    with op.batch_alter_table("admin_sessions") as batch:
        batch.drop_constraint("fk_admin_sessions_user", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_table("users")
