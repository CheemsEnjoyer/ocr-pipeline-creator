"""Baseline: create new databases and adopt the existing OCR schema without deleting data."""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('admin_sessions'):
        op.create_table('admin_sessions',
            sa.Column('token_hash', sa.String(length=64), nullable=False, primary_key=True),
            sa.Column('admin_hash', sa.String(length=64), nullable=False, primary_key=False),
            sa.Column('expires_at', sa.Integer(), nullable=False, primary_key=False),
        )
    if not inspector.has_table('api_keys'):
        op.create_table('api_keys',
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('name', sa.String(length=120), nullable=False, primary_key=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False, primary_key=False),
            sa.Column('prefix', sa.String(length=20), nullable=False, primary_key=False),
            sa.Column('pipeline_ids', sa.JSON(), nullable=False, primary_key=False),
            sa.Column('created_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('revoked_at', sa.String(length=32), nullable=True, primary_key=False),
            sa.UniqueConstraint('token_hash'),
        )
    if not inspector.has_table('documents'):
        op.create_table('documents',
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('filename', sa.Text(), nullable=False, primary_key=False),
            sa.Column('mime_type', sa.Text(), nullable=False, primary_key=False),
            sa.Column('size', sa.Integer(), nullable=False, primary_key=False),
            sa.Column('pipeline_name', sa.Text(), nullable=False, primary_key=False),
            sa.Column('original_key', sa.Text(), nullable=False, primary_key=False),
            sa.Column('text', sa.Text(), nullable=False, primary_key=False),
            sa.Column('result', sa.Text(), nullable=False, primary_key=False),
            sa.Column('fields', sa.JSON(), nullable=False, primary_key=False),
            sa.Column('created_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('updated_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('revision', sa.Integer(), nullable=False, primary_key=False),
            sa.Column('pipeline_id', sa.String(length=80), nullable=True, primary_key=False),
            sa.Column('api_key_id', sa.String(length=36), nullable=True, primary_key=False),
        )
    if not inspector.has_table('pipelines'):
        op.create_table('pipelines',
            sa.Column('id', sa.String(length=80), nullable=False, primary_key=True),
            sa.Column('config', sa.JSON(), nullable=False, primary_key=False),
            sa.Column('created_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('updated_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('deleted', sa.Integer(), nullable=False, primary_key=False),
        )
    if not inspector.has_table('processing_jobs'):
        op.create_table('processing_jobs',
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('status', sa.String(length=16), nullable=False, primary_key=False),
            sa.Column('filename', sa.Text(), nullable=False, primary_key=False),
            sa.Column('mime_type', sa.Text(), nullable=False, primary_key=False),
            sa.Column('size', sa.Integer(), nullable=False, primary_key=False),
            sa.Column('original_key', sa.Text(), nullable=False, primary_key=False),
            sa.Column('pipeline', sa.JSON(), nullable=False, primary_key=False),
            sa.Column('pipeline_id', sa.String(length=80), nullable=True, primary_key=False),
            sa.Column('api_key_id', sa.String(length=36), nullable=True, primary_key=False),
            sa.Column('error', sa.Text(), nullable=True, primary_key=False),
            sa.Column('created_at', sa.String(length=32), nullable=False, primary_key=False),
            sa.Column('updated_at', sa.String(length=32), nullable=False, primary_key=False),
        )
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    for name, length in (("pipeline_id", 80), ("api_key_id", 36)):
        if name not in columns:
            op.add_column("documents", sa.Column(name, sa.String(length), nullable=True))
    if 'idx_documents_api_key' not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes('documents')}:
        op.create_index('idx_documents_api_key', 'documents', ['api_key_id', 'created_at', 'id'], unique=False)
    if 'idx_documents_created_at' not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes('documents')}:
        op.create_index('idx_documents_created_at', 'documents', ['created_at', 'id'], unique=False)
    if 'idx_processing_jobs_api_key' not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes('processing_jobs')}:
        op.create_index('idx_processing_jobs_api_key', 'processing_jobs', ['api_key_id', 'created_at'], unique=False)

def downgrade():
    raise RuntimeError("Baseline downgrade is disabled to protect adopted data.")
