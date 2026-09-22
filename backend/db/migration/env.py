from alembic import context

from backend.db.infra.engine import configured_database_url, open_database
from backend.db.domain.models import Base

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("These migrations inspect existing tables; run an online upgrade instead of --sql")
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        run(connection)
    else:
        engine, _ = open_database(configured_database_url())
        try:
            with engine.begin() as connection:
                if engine.dialect.name == "postgresql":
                    from sqlalchemy import text
                    connection.execute(text("SELECT pg_advisory_xact_lock(748390215)"))
                run(connection)
        finally:
            engine.dispose()
