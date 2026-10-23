"""Persistent events and admission decisions against isolated databases."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.network import Node, NetworkLink
from backend.models.routing_event import RoutingEvent
from tests import test_routing as fixtures


class SavedRoutingTests(unittest.TestCase):
    setUp = fixtures.RoutingTests.setUp
    tearDown = fixtures.RoutingTests.tearDown

    def create(self, **kwargs):
        body = {"scenario_id": self.scenario_id, "lat": 0, "lng": 0,
                "policy": "static", "load_ratio": 0, "topology": "configured",
                "access_radius_km": 1, "target_id": "G1", **kwargs}
        response = self.client.post('/api/routing/events', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['data']

    def test_persists_across_clients_and_recompute_excludes_own_allocation(self):
        saved = self.create(required_bandwidth_mbps=60)
        self.assertEqual(saved['result']['route']['path'], ['A', 'B', 'G1'])
        restored = TestClient(app).get('/api/routing/events').json()['data']
        self.assertEqual(restored, [saved])
        updated = self.client.put(f"/api/routing/events/{saved['id']}", json={
            **saved['config'], 'lat': 0, 'lng': 0, 'service': saved['service']})
        self.assertEqual(updated.status_code, 200, updated.text)
        allocation = updated.json()['data']['result']['allocation']
        self.assertEqual(allocation['other_event_count'], 0)
        self.assertEqual(allocation['nodes'][0]['remaining_after_mbps'], 40)

    def test_shares_nodes_when_possible_and_never_overallocates(self):
        first = self.create(required_bandwidth_mbps=30)
        second = self.create(required_bandwidth_mbps=30)
        self.assertEqual(first['result']['route']['path'], second['result']['route']['path'])
        self.assertEqual(second['result']['allocation']['nodes'][0]['reserved_before_mbps'], 30)
        self.assertEqual(second['result']['allocation']['nodes'][0]['remaining_after_mbps'], 40)
        blocked = self.create(required_bandwidth_mbps=50)
        self.assertIsNone(blocked['result']['route'])
        self.assertEqual(blocked['result']['code'], 'no_path')
        self.assertIn('2 điểm', blocked['result']['reason'])
        self.assertEqual(self.client.get('/api/routing/events').json()['data'][0]['result'], first['result'])

    def test_selects_another_ingress_when_first_node_is_full(self):
        first = self.create(lng=.2, access_radius_km=None, target_id=None, required_bandwidth_mbps=80)
        second = self.create(lng=.2, access_radius_km=None, target_id=None, required_bandwidth_mbps=80)
        self.assertEqual(first['result']['route']['path'], ['G1'])
        self.assertEqual(second['result']['route']['path'], ['G2'])

    def test_shared_link_is_limited_and_delete_releases_capacity(self):
        with self.session() as db:
            db.query(Node).update({'bandwidth': 200})
            db.query(NetworkLink).update({'bandwidth': 70})
            db.commit()
        first = self.create(required_bandwidth_mbps=30)
        second = self.create(required_bandwidth_mbps=30)
        self.assertEqual(second['result']['allocation']['links'][0]['remaining_after_mbps'], 10)
        blocked = self.create(required_bandwidth_mbps=20)
        self.assertIsNone(blocked['result']['route'])
        response = self.client.delete(f"/api/routing/events/{first['id']}")
        self.assertEqual(response.status_code, 200)
        admitted = self.create(required_bandwidth_mbps=20)
        self.assertIsNotNone(admitted['result']['route'])
        ids = [event['id'] for event in TestClient(app).get('/api/routing/events').json()['data']]
        self.assertNotIn(first['id'], ids)

    def test_create_retry_is_idempotent_and_scenarios_are_isolated(self):
        first = self.create(client_key='same-browser-request', required_bandwidth_mbps=80)
        retry = self.create(client_key='same-browser-request', required_bandwidth_mbps=80)
        self.assertEqual(first, retry)
        other = self.create(scenario_id=self.other_id, target_id='FOREIGN', access_radius_km=None,
                            required_bandwidth_mbps=80)
        self.assertEqual(other['result']['allocation']['other_event_count'], 0)
        self.assertEqual(len(self.client.get(f'/api/routing/events?scenario_id={self.scenario_id}').json()['data']), 1)

    def test_explicit_recompute_releases_failed_route_but_not_other_reservations(self):
        first = self.create(required_bandwidth_mbps=60)
        response = self.client.put(f"/api/routing/events/{first['id']}", json={
            **first['config'], 'lat': 90, 'lng': 0, 'service': first['service']})
        self.assertIsNone(response.json()['data']['result']['route'])
        self.assertIsNotNone(self.create(required_bandwidth_mbps=60)['result']['route'])

    def test_playback_is_persisted_clamped_and_snapshot_scoped(self):
        saved = self.create()
        with self.session() as db:
            event = db.get(RoutingEvent, saved['id'])
            event.result_json = {**event.result_json, 'mobility': {'eta_s': 10, 'moves': [{'node_id': 'A'}]}}
            db.commit()
        url = f"/api/routing/events/{saved['id']}/playback"
        data = {'snapshot_at': saved['result']['snapshot_at'], 'elapsed_s': 5, 'paused': True}
        self.assertEqual(self.client.patch(url, json=data).json()['data']['elapsed_s'], 5)
        self.assertEqual(self.client.patch(url, json={**data, 'elapsed_s': 2}).json()['data']['elapsed_s'], 5)
        restored = self.client.get('/api/routing/events').json()['data'][0]
        self.assertTrue(restored['playback']['paused'])
        self.assertEqual(self.client.patch(url, json={**data, 'elapsed_s': 999}).json()['data']['elapsed_s'], 10)
        self.assertEqual(self.client.patch(url, json={**data, 'snapshot_at': 'old'}).status_code, 409)

    def test_unknown_event_and_cross_scenario_update_are_rejected(self):
        saved = self.create()
        response = self.client.put(f"/api/routing/events/{saved['id']}", json={
            **saved['config'], 'scenario_id': self.other_id, 'lat': 0, 'lng': 0})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.delete('/api/routing/events/999999').status_code, 404)

    def test_numbering_restarts_after_last_point_is_deleted(self):
        first, second = self.create(), self.create()
        self.assertEqual([first['name'], second['name']], ['Điểm 1', 'Điểm 2'])
        self.client.delete(f"/api/routing/events/{first['id']}")
        remaining = self.client.get('/api/routing/events').json()['data']
        self.assertEqual(remaining[0]['name'], 'Điểm 2')
        self.client.delete(f"/api/routing/events/{second['id']}")
        new = self.create()
        self.assertEqual(new['name'], 'Điểm 1')
        self.assertNotIn(new['id'], [first['id'], second['id']])
        self.assertEqual(self.client.get('/api/routing/events').json()['data'][0]['name'], 'Điểm 1')

    def test_bulk_delete_is_scoped_releases_capacity_and_restarts_numbering(self):
        self.create(required_bandwidth_mbps=60)
        self.create(required_bandwidth_mbps=50)
        other = self.create(scenario_id=self.other_id, target_id='FOREIGN', access_radius_km=None)
        response = self.client.delete(f'/api/routing/events?scenario_id={self.scenario_id}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['data']['deleted_count'], 2)
        remaining = self.client.get('/api/routing/events').json()['data']
        self.assertEqual([event['id'] for event in remaining], [other['id']])
        self.assertEqual(self.client.delete(f'/api/routing/events?scenario_id={self.scenario_id}').json()['data']['deleted_count'], 0)
        new = self.create(required_bandwidth_mbps=60)
        self.assertEqual(new['name'], 'Điểm 1')
        self.assertEqual(new['result']['allocation']['other_event_count'], 0)

    def test_background_load_reduction_never_uses_reserved_bandwidth(self):
        self.create(required_bandwidth_mbps=60)
        blocked = self.create(required_bandwidth_mbps=50, load_ratio=.8, allow_load_reduction=True)
        self.assertIsNone(blocked['result']['route'])
        self.assertEqual(len(self.client.get('/api/routing/events').json()['data']), 2)

    def test_deploying_node_cannot_accept_another_flow_until_it_arrives(self):
        saved = self.create(required_bandwidth_mbps=10)
        with self.session() as db:
            event = db.get(RoutingEvent, saved['id'])
            event.result_json = {**event.result_json, 'mobility': {'eta_s': 10, 'moves': [{
                'node_id': 'A', 'to': {'lat': 0, 'lng': 0, 'alt': 0}}]}}
            db.commit()
        self.assertIsNone(self.create(required_bandwidth_mbps=10)['result']['route'])
        response = self.client.patch(f"/api/routing/events/{saved['id']}/playback", json={
            'snapshot_at': saved['result']['snapshot_at'], 'elapsed_s': 10, 'paused': False})
        self.assertEqual(response.status_code, 200)
        # Adaptive links can reuse this deployed SEA node at its reserved position.
        self.assertIsNotNone(self.create(required_bandwidth_mbps=10, topology='adaptive')['result']['route'])

    def test_deployed_position_survives_deletion_of_original_moving_event(self):
        from backend.services.routing_event_service import reservations_for
        saved = self.create(required_bandwidth_mbps=10)
        with self.session() as db:
            event = db.get(RoutingEvent, saved['id'])
            result = event.result_json
            positions = [{**node, 'lng': .01} if node['id'] == 'A' else node for node in result['route']['positions']]
            event.result_json = {**result, 'route': {**result['route'], 'positions': positions},
                                 'mobility': {'eta_s': 10, 'moves': [{'node_id': 'A', 'to': {'lat': 0, 'lng': .01, 'alt': 0}}]}}
            event.playback_json = {'elapsed_s': 10, 'paused': False}
            db.commit()
        shared = self.create(lng=.01, required_bandwidth_mbps=10, topology='adaptive')
        self.assertEqual(shared['result']['route']['positions'][0]['lng'], .01)
        self.client.delete(f"/api/routing/events/{saved['id']}")
        with self.session() as db:
            reserved = reservations_for(db, self.scenario_id)
            self.assertEqual(reserved['positions']['A']['lng'], .01)

    def test_training_and_event_are_committed_together_and_retry_is_not_duplicated(self):
        from backend.models.simulation import Experiment
        with patch('backend.routers.federated_learning._network_config', return_value={'task': 'network_delay'}), \
                patch('backend.services.fl_service.run_experiment') as training:
            first = self.create(policy='predictive', auto_train=True, client_key='training-point')
            retry = self.create(policy='predictive', auto_train=True, client_key='training-point')
        self.assertEqual(first['result']['code'], 'training')
        self.assertEqual(first, retry)
        self.assertEqual(training.call_count, 1)
        with self.session() as db:
            self.assertEqual(db.query(Experiment).count(), 1)
            self.assertEqual(db.query(RoutingEvent).count(), 1)

    def test_concurrent_creates_cannot_reserve_the_same_bandwidth_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.database.database import Base, get_db
        from backend.models.scenario import Scenario

        with TemporaryDirectory() as folder:
            engine = create_engine('sqlite:///' + (Path(folder) / 'concurrent.sqlite').as_posix())
            sessions = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            with sessions() as db:
                scenario = Scenario(name='Concurrent'); db.add(scenario); db.flush()
                scenario_id = scenario.id
                db.add(Node(id='GROUND', type='GROUND', lat=0, lng=0, alt=0, bandwidth=100,
                            latency=1, status='ACTIVE', scenario_id=scenario_id))
                db.commit()
            def isolated_db():
                with sessions() as db:
                    yield db
            app.dependency_overrides[get_db] = isolated_db
            def submit(index):
                response = TestClient(app).post('/api/routing/events', json={
                    'scenario_id': scenario_id, 'lat': 0, 'lng': 0, 'policy': 'static',
                    'load_ratio': 0, 'required_bandwidth_mbps': 60, 'client_key': f'parallel-{index}'})
                self.assertEqual(response.status_code, 201, response.text)
                return response.json()['data']
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    events = list(pool.map(submit, range(2)))
                self.assertEqual(sum(bool(event['result']['route']) for event in events), 1)
                with sessions() as db:
                    self.assertEqual(db.query(RoutingEvent).count(), 2)
            finally:
                engine.dispose()


if __name__ == '__main__':
    unittest.main()
