"""Device feasibility is enforced before checkpoint-based route selection."""
import unittest
from unittest.mock import patch

from backend.models.network import Node, NetworkLink
from backend.services import routing_service
from tests import test_routing as fixtures


class EventDeviceTests(unittest.TestCase):
    setUp = fixtures.RoutingTests.setUp
    tearDown = fixtures.RoutingTests.tearDown
    save_model = fixtures.RoutingTests.save_model

    def request(self, **kwargs):
        response = self.client.post('/api/routing/event', json={
            'scenario_id': self.scenario_id, 'lat': 0, 'lng': .2,
            'policy': 'static', 'load_ratio': 0, **kwargs})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def test_automatic_device_traffic_and_destination_for_every_service(self):
        for service in ('Message', 'Video Call', 'Watch Video', 'Gaming', 'Emergency'):
            with self.subTest(service=service):
                result = self.request(service=service)
                self.assertEqual(result['code'], 'ok', result)
                self.assertEqual(result['event_model']['device']['id'],
                                 'emergency_radio' if service == 'Emergency' else 'smartphone')
                self.assertEqual(result['event_model']['selection'], 'automatic')
                self.assertEqual(result['destination']['node_id'], result['route']['targetId'])
                self.assertGreater(result['route']['application']['endpoint_processing_ms'], 0)
                self.assertLessEqual(result['route']['access']['bandwidth_mbps'],
                                     result['event_model']['device']['effective_bandwidth_mbps'])

    def test_handset_cannot_use_far_ground_or_direct_satellite_even_in_global_scope(self):
        with self.session() as db:
            db.get(Node, 'A').status = 'OFFLINE'
            db.get(Node, 'B').status = 'OFFLINE'
            db.get(Node, 'G1').lng = 10
            db.get(Node, 'G2').lng = 15
            db.add(Node(id='SAT', type='SPACE', lat=0, lng=0, alt=1200,
                        bandwidth=100, latency=5, status='ACTIVE', scenario_id=self.scenario_id))
            db.flush()
            db.add(NetworkLink(source='SAT', target='G1', distance=1700, bandwidth=100, latency=6, status='ACTIVE'))
            db.commit()
        phone = self.request(lng=0, routing_scope='global')
        self.assertEqual(phone['code'], 'no_coverage')
        diagnostics = phone['coverage_diagnostics']['nearest_compatible_nodes']
        self.assertTrue(diagnostics)
        self.assertTrue(all(row['type'] != 'SPACE' for row in diagnostics))
        self.assertTrue(all(not row['within_device_range'] for row in diagnostics))
        terminal = self.request(lng=0, routing_scope='global', source_device='satellite_terminal')
        self.assertEqual(terminal['code'], 'ok', terminal)
        self.assertEqual(terminal['route']['sourceId'], 'SAT')
        local = self.request(lng=0, source_device='satellite_terminal')
        self.assertIsNone(local['route'])

    def test_gateway_chooses_nearest_feasible_ingress_before_fl_scoring(self):
        identifier = self.save_model()
        with patch.object(routing_service, 'predict', wraps=routing_service.predict) as inference:
            result = self.request(lng=0, routing_scope='global', source_device='network_gateway',
                topology='configured', policy='predictive', experiment_id=identifier)
        self.assertEqual(result['code'], 'ok', result)
        self.assertEqual(result['route']['sourceId'], 'A')
        self.assertEqual(result['baseline']['sourceId'], 'A')
        self.assertEqual(result['ingress_selection']['method'], 'nearest_feasible')
        self.assertFalse(result['route']['access']['virtual'])
        inference.assert_called_once()
        # A deliberately cheap prediction for a farther source cannot change ingress.
        with patch.object(routing_service, 'predict', side_effect=lambda model, rows: [0.01]*len(rows)):
            changed = self.request(lng=0, routing_scope='global', source_device='network_gateway',
                topology='configured', policy='predictive', experiment_id=identifier)
        self.assertEqual(changed['route']['sourceId'], 'A')

    def test_gateway_skips_nearest_if_disconnected_or_out_of_capacity(self):
        for failure in ('disconnected', 'capacity'):
            with self.subTest(failure=failure), self.session() as db:
                if failure == 'disconnected':
                    db.query(NetworkLink).filter((NetworkLink.source=='A') | (NetworkLink.target=='A')).update({'status':'INACTIVE'})
                else:
                    db.query(NetworkLink).filter(NetworkLink.target != 'FOREIGN').update({'status':'ACTIVE'})
                    db.get(Node, 'A').bandwidth = .001
                db.commit()
            result = self.request(lng=0, routing_scope='global', source_device='network_gateway', topology='configured')
            self.assertEqual(result['code'], 'ok', result)
            self.assertEqual(result['route']['sourceId'], 'B')

    def test_gateway_does_not_connect_to_distant_surface_nodes(self):
        for lat, lng in ((0, 180), (85, -120), (-85, 50)):
            result = self.request(lat=lat, lng=lng, routing_scope='global', source_device='network_gateway')
            self.assertEqual(result['code'], 'no_coverage', result)
            self.assertIsNone(result['route'])

    def test_local_failure_keeps_nearest_access_diagnostics(self):
        result = self.request(lat=70, lng=100)
        self.assertEqual(result['code'], 'no_local_nodes')
        nearest = result['coverage_diagnostics']['nearest_compatible_nodes']
        self.assertTrue(nearest)
        self.assertTrue(all(not node['within_local_scope'] for node in nearest))
        self.assertIsNone(result['route'])

    def test_device_bandwidth_and_elevation_limit_are_hard_constraints(self):
        result = self.request(service='Video Call', source_device='iot_sensor')
        self.assertEqual(result['code'], 'device_capacity')
        from backend.services.event_device_service import elevation_deg
        from types import SimpleNamespace
        origin = SimpleNamespace(lat=0, lng=0)
        self.assertAlmostEqual(elevation_deg(origin, SimpleNamespace(lat=0, lng=0, alt=1200)), 90)
        self.assertLess(elevation_deg(origin, SimpleNamespace(lat=0, lng=31, alt=1200)), 10)

    def test_real_checkpoint_is_used_after_device_filter_and_can_change_selection(self):
        identifier = self.save_model()
        with self.session() as db:
            db.get(Node, 'G1').lng = .01
            db.get(Node, 'G2').lng = .02
            db.get(Node, 'A').status = 'OFFLINE'
            db.get(Node, 'B').status = 'OFFLINE'
            db.commit()
        with patch.object(routing_service, 'predict', wraps=routing_service.predict) as inference:
            result = self.request(lng=0, policy='predictive', experiment_id=identifier)
        self.assertEqual(result['code'], 'ok', result)
        inference.assert_called_once()
        self.assertEqual(result['routing_decision']['experiment_id'], identifier)
        self.assertEqual(result['routing_decision']['method'], 'fl_checkpoint')
        self.assertIsNotNone(result['route']['predicted_access_rtt_ms'])
        self.assertTrue(all(row['layer'] == 'GROUND' for row in inference.call_args.args[1]))
        # Controlled prediction change demonstrates the ranking actually uses
        # model outputs, rather than merely displaying a checkpoint label.
        with patch.object(routing_service, 'predict', side_effect=lambda model, rows:
                          [.01 if row['latency_ms'] > 2 else 1000 for row in rows]):
            changed = self.request(lng=0, policy='predictive', experiment_id=identifier)
        self.assertEqual(changed['baseline']['path'], ['G1'])
        self.assertEqual(changed['route']['path'], ['G2'])

    def test_saved_event_records_resolved_device_without_upgrading_it(self):
        response = self.client.post('/api/routing/events', json={
            'scenario_id': self.scenario_id, 'lat': 0, 'lng': .2,
            'service': 'Emergency', 'policy': 'static'})
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()['data']
        restored = self.client.get('/api/routing/events').json()['data'][0]
        self.assertEqual(saved, restored)
        self.assertEqual(restored['config']['source_device'], 'auto')
        self.assertEqual(restored['result']['event_model']['device']['id'], 'emergency_radio')


if __name__ == '__main__':
    unittest.main()
