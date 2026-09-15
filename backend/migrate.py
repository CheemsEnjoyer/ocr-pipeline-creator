from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from .database import configured_database_url, open_database


def migrate(engine):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(748390215)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


if __name__ == "__main__":
    engine, _ = open_database(configured_database_url())
    try:
        migrate(engine)
    finally:
        engine.dispose()
