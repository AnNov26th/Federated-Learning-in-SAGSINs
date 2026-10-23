"""Upgrading saved points must work on old tables as well as empty databases."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.database import Base, get_db
from backend.database.init_db import init_db
from backend.database.routing_migrations import migrate_routing_events
from backend.main import app
from backend.models.network import Node
from backend.models.routing_event import RoutingEvent
from backend.models.scenario import Scenario


class RoutingSchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        # Reproduce the actual database that create_all left unchanged: the old
        # saved-event table exists, but has never had an idempotency-key column.
        with self.engine.begin() as connection:
            connection.execute(text('''CREATE TABLE routing_events (
                id INTEGER PRIMARY KEY, scenario_id INTEGER NOT NULL, service VARCHAR(30) NOT NULL,
                lat FLOAT NOT NULL, lng FLOAT NOT NULL, config_json JSON NOT NULL, result_json JSON NOT NULL,
                playback_json JSON, created_at DATETIME NOT NULL
            )'''))
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            scenario = Scenario(name='Old schema'); db.add(scenario); db.flush()
            self.scenario_id = scenario.id
            db.add(Node(id='GROUND', type='GROUND', lat=0, lng=0, alt=0, bandwidth=100,
                        latency=1, status='ACTIVE', scenario_id=scenario.id))
            db.commit()

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    def test_upgrades_existing_rows_preserves_data_and_is_repeatable(self):
        result = {'status': 'unavailable', 'route': None, 'reason': 'saved reason'}
        with self.engine.begin() as connection:
            for event_id in (11, 12):
                connection.execute(text('''INSERT INTO routing_events
                    (id, scenario_id, service, lat, lng, config_json, result_json, created_at)
                    VALUES (:id, :scenario, 'Gaming', 10, 106, :config, :result, '2026-10-23 00:00:00')'''),
                    {'id': event_id, 'scenario': self.scenario_id, 'config': json.dumps({'policy': 'static'}),
                     'result': json.dumps(result)})
        migrate_routing_events(self.engine)
        with self.sessions() as db:
            rows = db.query(RoutingEvent).order_by(RoutingEvent.id).all()
            keys = [row.client_key for row in rows]
            self.assertEqual([row.id for row in rows], [11, 12])
            self.assertEqual([row.display_number for row in rows], [11, 12])
            self.assertEqual(len(set(keys)), 2)
            self.assertTrue(all(keys))
            self.assertTrue(all(row.result_json == result and row.config_json == {'policy': 'static'} for row in rows))
            self.assertTrue(all((row.lat, row.lng) == (10, 106) for row in rows))
        migrate_routing_events(self.engine)
        with self.sessions() as db:
            self.assertEqual([row.client_key for row in db.query(RoutingEvent).order_by(RoutingEvent.id)], keys)
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text('UPDATE routing_events SET client_key = :key WHERE id = 12'), {'key': keys[0]})

    def test_normal_startup_repairs_schema_then_api_can_save_and_route(self):
        with patch('backend.database.init_db.apply_data_migrations'):
            init_db(bind=self.engine)
        self.assertIn('client_key', {column['name'] for column in inspect(self.engine).get_columns('routing_events')})
        def isolated_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        client = TestClient(app)
        self.assertEqual(client.get('/api/routing/events').status_code, 200)
        response = client.post('/api/routing/events', json={
            'scenario_id': self.scenario_id, 'lat': 0, 'lng': 0, 'policy': 'static', 'load_ratio': 0})
        self.assertEqual(response.status_code, 201, response.text)
        event = response.json()['data']
        self.assertEqual(event['result']['route']['path'], ['GROUND'])
        self.assertEqual(event['name'], 'Điểm 1')
        self.assertEqual(client.get('/api/routing/events').json()['data'][0]['id'], event['id'])
