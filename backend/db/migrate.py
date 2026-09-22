from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from .infra.engine import configured_database_url, open_database


def ensure_database(engine):
    if engine.dialect.name != "postgresql":
        return
    # Existing databases need neither access to postgres nor CREATEDB privileges.
    try:
        with engine.connect():
            return
    except OperationalError as error:
        connection_error = error

    name = engine.url.database
    if not name:
        raise connection_error
    maintenance, _ = open_database(engine.url.set(database="postgres"))
    try:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            # Serialize creation across application instances; CREATE DATABASE cannot
            # run inside a transaction, so this lock is session-scoped.
            connection.execute(text("SELECT pg_advisory_lock(748390216)"))
            try:
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                ).scalar()
                if exists:
                    # Do not turn authentication/access failures into creation attempts.
                    with engine.connect():
                        return
                identifier = maintenance.dialect.identifier_preparer.quote_identifier(name)
                try:
                    connection.exec_driver_sql(f"CREATE DATABASE {identifier}")
                except DBAPIError as error:
                    state = getattr(error.orig, "sqlstate", None)
                    if state == "42501":
                        raise RuntimeError(
                            "База PostgreSQL отсутствует. Для автоматического создания "
                            "выдайте пользователю право CREATEDB или создайте базу вручную."
                        ) from error
                    if state != "42P04":  # Another administrator created it concurrently.
                        raise
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(748390216)"))
    finally:
        maintenance.dispose()


def migrate(engine):
    ensure_database(engine)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migration"))
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
