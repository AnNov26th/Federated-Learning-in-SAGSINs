"""Only the broken legacy store is isolated; core/API failures stay visible."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pymysql.err import OperationalError as DriverError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.database.database import Base, get_db
from backend.database.storage_health import (
    LEGACY_TABLE, _unavailable, inspect_legacy_store, unavailable_tables,
)
from backend.main import app
from backend.models.network import Node
from backend.models.network_learning import NetworkDataset
from backend.models.simulation import Experiment


class StorageProbeTests(unittest.TestCase):
    def probe(self, code):
        engine = MagicMock()
        engine.engine = engine
        engine.dialect.name = 'mysql'
        connection = engine.connect.return_value.__enter__.return_value
        connection.exec_driver_sql.side_effect = OperationalError(
            'SELECT 1', {}, DriverError(code, 'probe failure'))
        return engine, connection

    def test_1932_only_marks_optional_store_and_never_writes(self):
        engine, connection = self.probe(1932)
        self.assertEqual(inspect_legacy_store(engine), {LEGACY_TABLE: 1932})
        connection.exec_driver_sql.assert_called_once_with('SELECT 1 FROM network_observations LIMIT 0')

    def test_missing_table_is_created_normally_on_fresh_database(self):
        engine, _ = self.probe(1146)
        self.assertEqual(inspect_legacy_store(engine), {})

    def test_permission_and_connection_errors_are_not_hidden(self):
        for code in (1044, 1045, 2003, 2013):
            engine, _ = self.probe(code)
            with self.assertRaises(OperationalError):
                inspect_legacy_store(engine)

    def test_recovery_clears_previous_degraded_status(self):
        engine, connection = self.probe(1932)
        inspect_legacy_store(engine)
        connection.exec_driver_sql.side_effect = None
        self.assertEqual(inspect_legacy_store(engine), {})


class DegradedStartupTests(unittest.TestCase):
    def test_full_startup_lists_datasets_and_blocks_legacy_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = create_engine('sqlite:///' + (Path(folder) / 'test.sqlite').as_posix())
            Base.metadata.create_all(engine)
            blocked_queries = []

            def forbid_observations(conn, cursor, statement, parameters, context, many):
                if LEGACY_TABLE in statement.lower():
                    blocked_queries.append(statement)
                    raise AssertionError('An unavailable store must not be touched')

            event.listen(engine, 'before_cursor_execute', forbid_observations)

            def mark_unavailable(bind):
                _unavailable[bind] = {LEGACY_TABLE: 1932}
                return unavailable_tables(bind)

            def override_db():
                with Session(engine) as db:
                    yield db

            app.dependency_overrides[get_db] = override_db
            try:
                with patch('backend.main.engine', engine), \
                        patch('backend.database.storage_health.inspect_legacy_store', side_effect=mark_unavailable):
                    with TestClient(app) as client:
                        health = client.get('/api/health').json()
                        self.assertTrue(health['database_ready'])
                        self.assertEqual(health['status'], 'degraded')
                        self.assertTrue(health['warnings'])
                        self.assertEqual(client.get('/').status_code, 200)
                        with Session(engine) as db:
                            scenario = db.query(Node).first().scenario_id
                            config = dict(target='test', partition='non_iid', network_profile='normal',
                                          profiles={'client': {'layer': 'GROUND'}},
                                          samples_per_client=160, online_steps=0, locality='test')
                            legacy = NetworkDataset(scenario_id=scenario, seed=42,
                                                    generator_version='test', fingerprint='a' * 64,
                                                    config_json=config)
                            distributed = NetworkDataset(scenario_id=scenario, seed=42,
                                generator_version='test', fingerprint='b' * 64,
                                config_json={**config, 'runtime': 'federated-http-v3', 'counts': {'train': 93}})
                            db.add_all([legacy, distributed]); db.commit()
                            legacy_id, local_id = legacy.id, distributed.id
                        response = client.get('/api/fl/datasets')
                        self.assertEqual(response.status_code, 200)
                        rows = {r['id']: r for r in response.json()['data']}
                        self.assertFalse(rows[legacy_id]['available'])
                        self.assertFalse(rows[legacy_id]['counts_available'])
                        self.assertTrue(rows[local_id]['available'])
                        self.assertEqual(rows[local_id]['counts'], {'train': 93})
                        self.assertEqual(client.get(f'/api/fl/datasets/{legacy_id}/observations').status_code, 503)
                        self.assertEqual(client.get(f'/api/fl/datasets/{local_id}/observations').status_code, 403)
                        request = dict(task='network_delay', runtime='legacy', scenario_id=scenario,
                                       pool_mode='all', client_count=2, partition='non_iid')
                        self.assertEqual(client.post('/api/fl/experiments', json=request).status_code, 503)
                        self.assertEqual(client.post('/api/fl/datasets', json={'scenario_id': scenario}).status_code, 503)
                        with Session(engine) as db:
                            self.assertEqual(db.query(Experiment).count(), 0)
                        self.assertEqual(blocked_queries, [])
            finally:
                app.dependency_overrides.pop(get_db, None)
                _unavailable.pop(engine, None)
                engine.dispose()
