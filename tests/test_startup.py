"""Startup must identify DB failures and release unsuccessful coordinator locks."""
import unittest
from unittest.mock import MagicMock, patch

from backend.database.database import connection_options
from backend.main import acquire_coordinator_lock, app, lifespan, startup_failure_hint


class ConnectionTimeoutTests(unittest.TestCase):
    def test_storage_engine_error_has_specific_non_destructive_guidance(self):
        from pymysql.err import OperationalError
        from sqlalchemy.exc import OperationalError as SQLAlchemyError
        error = SQLAlchemyError('DESCRIBE network_observations', {},
                                OperationalError(1932, "Table doesn't exist in engine"))
        hint = startup_failure_hint(error)
        self.assertIn('1932', hint)
        self.assertIn('tablespace', hint)
        self.assertNotIn('handshake', hint)

    def test_mysql_bounds_handshake_and_query_waits(self):
        options = connection_options('mysql+pymysql://user@localhost/example')
        self.assertEqual(options, dict(connect_timeout=5, read_timeout=30, write_timeout=30))

    def test_sqlite_does_not_receive_mysql_options(self):
        self.assertEqual(connection_options('sqlite://'), {})

    def test_lock_query_failure_closes_connection(self):
        connection = MagicMock()
        connection.execute.side_effect = RuntimeError('database unavailable')
        with patch('backend.main.engine') as engine:
            engine.connect.return_value = connection
            with self.assertRaisesRegex(RuntimeError, 'database unavailable'):
                acquire_coordinator_lock()
        connection.close.assert_called_once()

    def test_existing_coordinator_is_rejected_and_connection_closed(self):
        connection = MagicMock()
        connection.execute.return_value.scalar.return_value = 0
        with patch('backend.main.engine') as engine:
            engine.connect.return_value = connection
            with self.assertRaisesRegex(RuntimeError, 'backend khác'):
                acquire_coordinator_lock()
        connection.close.assert_called_once()


class StartupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_stops_before_migrations(self):
        with patch('backend.main.acquire_coordinator_lock', side_effect=TimeoutError('handshake timed out')), \
                patch('backend.main.init_db') as initialize, \
                self.assertLogs('uvicorn.error', level='INFO') as logs:
            with self.assertRaisesRegex(TimeoutError, 'handshake timed out'):
                async with lifespan(app):
                    self.fail('Failed startup must not serve requests')
        initialize.assert_not_called()
        self.assertFalse(app.state.database_ready)
        self.assertIn('kết nối database', '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
