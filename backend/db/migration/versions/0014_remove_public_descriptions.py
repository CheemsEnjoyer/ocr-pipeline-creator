from copy import deepcopy

from alembic import op
import sqlalchemy as sa

revision = "0014_remove_public_descriptions"
down_revision = "0013_task_content_type"
branch_labels = None
depends_on = None


def clean_fields(fields):
    if not isinstance(fields, list):
        return
    for field in fields:
        if isinstance(field, dict):
            field.pop("public_description", None)
            clean_fields(field.get("fields"))


def clean_pipeline(config):
    if not isinstance(config, dict):
        return
    config.pop("description", None)
    extraction = config.get("extraction")
    if isinstance(extraction, dict):
        clean_fields(extraction.get("fields"))


def clean_schema(schema):
    if not isinstance(schema, dict):
        return
    schema.pop("description", None)
    for value in schema.get("properties", {}).values():
        clean_schema(value)
    clean_schema(schema.get("items"))
    for keyword in ("anyOf", "allOf", "oneOf"):
        for value in schema.get(keyword, []):
            clean_schema(value)


def upgrade():
    connection = op.get_bind()
    for name, column_name, clean in (
        ("pipelines", "config", clean_pipeline),
        ("processing_jobs", "pipeline", clean_pipeline),
        ("documents", "result_schema", clean_schema),
    ):
        table = sa.table(name, sa.column("id", sa.String), sa.column(column_name, sa.JSON))
        last_id = None
        while True:
            query = sa.select(table.c.id, table.c[column_name]).order_by(table.c.id).limit(500)
            if last_id is not None:
                query = query.where(table.c.id > last_id)
            rows = connection.execute(query).all()
            if not rows:
                break
            for row_id, value in rows:
                cleaned = deepcopy(value)
                clean(cleaned)
                if cleaned != value:
                    connection.execute(table.update().where(table.c.id == row_id).values({column_name: cleaned}))
            last_id = rows[-1][0]


def downgrade():
    pass
