import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import OperationalError, ProgrammingError

from backend.db.migrate import ensure_database


class DatabaseCreationTests(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        self.engine.dialect.name = "postgresql"
        self.engine.url = make_url('postgresql+psycopg://user:secret@db:5433/ocr?sslmode=require')
        self.failure = OperationalError(None, None, Exception("connection failed"))
        self.maintenance = MagicMock()
        self.maintenance.dialect = dialect()
        self.connection = self.maintenance.connect.return_value.execution_options.return_value.__enter__.return_value
        self.connection.execute.return_value.scalar.return_value = None
        self.opener = patch("backend.db.migrate.open_database", return_value=(self.maintenance, None))
        self.open_database = self.opener.start()
        self.addCleanup(self.opener.stop)

    def test_existing_database_does_not_require_maintenance_access(self):
        ensure_database(self.engine)
        self.open_database.assert_not_called()

    def test_sqlite_is_unchanged(self):
        self.engine.dialect.name = "sqlite"
        ensure_database(self.engine)
        self.engine.connect.assert_not_called()

    def test_missing_database_uses_same_server_and_quotes_identifier(self):
        self.engine.connect.side_effect = self.failure
        self.engine.url = self.engine.url.set(database='ocr"; DROP DATABASE postgres; --')
        ensure_database(self.engine)
        self.open_database.assert_called_once_with(self.engine.url.set(database="postgres"))
        self.maintenance.connect.return_value.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
        self.connection.exec_driver_sql.assert_called_once_with('CREATE DATABASE "ocr""; DROP DATABASE postgres; --"')
        self.assertIn("pg_advisory_unlock", str(self.connection.execute.call_args.args[0]))
        self.maintenance.dispose.assert_called_once()

    def test_existing_but_inaccessible_database_is_not_created(self):
        self.engine.connect.side_effect = self.failure
        self.connection.execute.return_value.scalar.return_value = 1
        with self.assertRaises(OperationalError):
            ensure_database(self.engine)
        self.connection.exec_driver_sql.assert_not_called()
        self.maintenance.dispose.assert_called_once()

    def test_database_created_by_another_process_is_reused(self):
        self.engine.connect.side_effect = [self.failure, MagicMock()]
        self.connection.execute.return_value.scalar.return_value = 1
        ensure_database(self.engine)
        self.connection.exec_driver_sql.assert_not_called()

    def test_missing_createdb_permission_has_actionable_error(self):
        self.engine.connect.side_effect = self.failure
        original = Exception("permission denied")
        original.sqlstate = "42501"
        self.connection.exec_driver_sql.side_effect = ProgrammingError(None, None, original)
        with self.assertRaisesRegex(RuntimeError, "CREATEDB"):
            ensure_database(self.engine)
        self.assertIn("pg_advisory_unlock", str(self.connection.execute.call_args.args[0]))
        self.maintenance.dispose.assert_called_once()

    def test_maintenance_connection_failure_does_not_create_database(self):
        self.engine.connect.side_effect = self.failure
        self.maintenance.connect.side_effect = self.failure
        with self.assertRaises(OperationalError):
            ensure_database(self.engine)
        self.connection.exec_driver_sql.assert_not_called()
        self.maintenance.dispose.assert_called_once()
