"""Routing decisions, model inference and failures against an isolated DB."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.database import Base, get_db
from backend.main import app
from backend.algorithms.network_delay_model import NetworkDelayRegressor, checkpoint
from backend.models.network import Node, NetworkLink
from backend.models.network_learning import NetworkRoundEvaluation
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound
from backend.services.network_dataset_service import create_dataset


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        with self.session() as db:
            s = Scenario(name='Routing', total_nodes=4)
            other = Scenario(name='Other')
            db.add_all([s, other]); db.flush()
            self.scenario_id, self.other_id = s.id, other.id
            for id, layer, lng, latency in [('A','SEA',0,1), ('B','AIR',.1,1), ('G1','GROUND',.2,1), ('G2','GROUND',.3,3)]:
                db.add(Node(id=id, type=layer, lat=0, lng=lng, alt=0, bandwidth=100, latency=latency,
                            status='ACTIVE', scenario_id=s.id))
            db.add(Node(id='FOREIGN', type='GROUND',lat=0,lng=.01,alt=0,bandwidth=500,latency=.1,status='ACTIVE',scenario_id=other.id))
            db.flush()
            for a,b,latency in [('A','B',1),('B','G1',1),('A','G2',3),('A','FOREIGN',.1)]:
                db.add(NetworkLink(source=a,target=b,distance=10,bandwidth=100,latency=latency,status='ACTIVE'))
            db.commit()
        def get_test_db():
            with self.session() as db:
                yield db
        app.dependency_overrides[get_db] = get_test_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    def request(self, **kwargs):
        response = self.client.post('/api/routing/event', json={'scenario_id':self.scenario_id,'lat':0,'lng':0,
                                                             'policy':'static','load_ratio':0,
                                                             'topology':'configured','access_radius_km':1, **kwargs})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['data']

    def save_model(self):
        with self.session() as db:
            dataset = create_dataset(db, self.scenario_id, samples_per_client=40)
            experiment = Experiment(scenario_id=self.scenario_id, algorithm='Predictive', status='COMPLETED',
                                    rounds=1,learning_rate=.01,config_json={'task':'network_delay','dataset_id':dataset.id})
            db.add(experiment); db.flush()
            round_row = FLRound(experiment_id=experiment.id,round=1,participants_count=2,accuracy=0,loss=.1,round_duration_s=.1)
            db.add(round_row); db.flush()
            db.add(NetworkRoundEvaluation(round_id=round_row.id,mae_ms=2,rmse_ms=3,validation_mae_ms=2,
                                          persistence_mae_ms=5,test_samples=8,selection_source='global_model_previous_round',
                                          checkpoint_json=checkpoint(NetworkDelayRegressor())))
            db.commit()
            return experiment.id

    def test_optimizes_across_destinations_and_does_not_cross_scenarios(self):
        result = self.request()
        self.assertEqual(result['route']['path'],['A','B','G1'])
        self.assertEqual(result['route']['hop_count'],2)
        self.assertEqual(result['route']['positions'][0]['id'],'A')
        self.assertNotIn('FOREIGN',result['route']['path'])

    def test_disconnection_never_implicitly_falls_back_to_virtual_links(self):
        with self.session() as db:
            db.query(NetworkLink).update({'status':'INACTIVE'}); db.commit()
        self.assertEqual(self.request()['code'],'no_path')
        self.assertEqual(self.request(topology='estimated')['status'],'routed')

    def test_prediction_requires_compatible_completed_fl_model(self):
        self.assertEqual(self.request(policy='predictive',experiment_id=999999)['code'],'no_model')
        experiment_id = self.save_model()
        result = self.request(policy='predictive')
        self.assertEqual(result['status'],'routed')
        self.assertEqual(result['model']['experiment_id'],experiment_id)
        # The actual zero-residual network is a persistence model, so inference
        # agrees with its current RTT inputs (and is not a fabricated score).
        for hop in result['route']['hops']:
            self.assertAlmostEqual(hop['predicted_ms'],hop['static_ms'],places=4)
        self.assertEqual(self.request(policy='predictive',experiment_id=experiment_id+99)['code'],'no_model')

    def test_model_output_changes_route_and_inference_is_batched(self):
        self.save_model()
        def predictions(model, features):
            # Make AIR expensive while allowing the alternate direct GROUND.
            return [1000 if f['layer'] == 'AIR' else 1 for f in features]
        with patch('backend.services.routing_service.predict',side_effect=predictions) as inference:
            result = self.request(policy='predictive')
        self.assertEqual(inference.call_count,1)
        self.assertEqual(result['route']['path'],['A','G2'])
        self.assertEqual(result['baseline']['path'],['A','B','G1'])
        self.assertFalse(result['comparison']['same_path'])
        self.assertEqual(result['route']['hops'][0]['predicted_ms'],1)

    def test_real_federated_checkpoint_is_reused_by_routing(self):
        with patch('backend.services.fl_service.SessionLocal',self.session):
            response = self.client.post('/api/fl/experiments',json={
                'task':'network_delay','scenario_id':self.scenario_id,'algorithm':'Predictive',
                'rounds':2,'client_count':2,'local_epochs':1,'samples_per_client':40,
                'batch_size':16,'learning_rate':.03,'timeout_ms':30000,
            })
        self.assertEqual(response.status_code,202,response.text)
        experiment_id = response.json()['data']['id']
        result = self.request(policy='predictive',experiment_id=experiment_id)
        self.assertEqual(result['status'],'routed')
        self.assertEqual(result['model']['round'],2)
        hop = result['route']['hops'][0]
        inference = self.client.post(f'/api/fl/experiments/{experiment_id}/predict',json=hop['features'])
        self.assertEqual(inference.status_code,200,inference.text)
        self.assertAlmostEqual(hop['predicted_ms'],inference.json()['data']['predicted_delay_ms'],places=3)
        access = result['route']['access']
        access_inference = self.client.post(f'/api/fl/experiments/{experiment_id}/predict', json=access['features'])
        self.assertEqual(access_inference.status_code, 200, access_inference.text)
        self.assertAlmostEqual(access['predicted_access_rtt_ms'], access_inference.json()['data']['predicted_delay_ms'], places=3)

    def test_bandwidth_filter_inactive_nodes_coverage_and_target(self):
        with self.session() as db:
            db.query(NetworkLink).update({'bandwidth':.5}); db.commit()
        self.assertEqual(self.request(service='Video Call')['code'],'no_path')
        self.assertEqual(self.request(service='Message')['status'],'routed')
        self.assertEqual(self.request(lat=80,lng=100,access_radius_km=10)['code'],'no_coverage')
        self.assertEqual(self.request(target_id='FOREIGN')['code'],'invalid_target')
        with self.session() as db:
            db.get(Node,'B').status='OFFLINE'; db.get(Node,'G2').status='OFFLINE'; db.commit()
        self.assertEqual(self.request()['code'],'no_path')

    def test_virtual_graph_does_not_bridge_uncovered_components(self):
        with self.session() as db:
            db.get(Node,'G1').lng=180; db.get(Node,'G2').lng=180; db.commit()
        self.assertEqual(self.request(topology='estimated')['code'],'no_path')

    def test_local_ground_target_and_source_capacity(self):
        result = self.request(lng=.2,target_id='G1')
        self.assertEqual(result['route']['path'],['G1'])
        self.assertEqual(result['route']['hop_count'],0)
        with self.session() as db:
            db.get(Node,'G1').bandwidth=.01; db.commit()
        self.assertEqual(self.request(lng=.2,target_id='G1')['code'],'no_path')

    def test_persisting_nearby_links_is_scoped_to_selected_scenario(self):
        with self.session() as db:
            db.add(Node(id='FOREIGN2',type='GROUND',lat=0,lng=.02,alt=0,bandwidth=100,
                        latency=1,status='ACTIVE',scenario_id=self.other_id))
            db.commit()
        response = self.client.post(f'/api/links/generate-nearby?scenario_id={self.other_id}')
        self.assertEqual(response.status_code,200,response.text)
        links = response.json()['data']['links']
        self.assertEqual(len(links),1)
        self.assertEqual({links[0]['source'],links[0]['target']},{'FOREIGN','FOREIGN2'})

    def test_estimated_satellite_link_respects_horizon(self):
        with self.session() as db:
            db.get(Node,'A').type='SPACE'; db.get(Node,'A').alt=550; db.get(Node,'A').lng=180
            db.get(Node,'B').status='OFFLINE'; db.commit()
        result = self.request(topology='estimated',target_id='G2',access_radius_km=10)
        self.assertEqual(result['code'],'no_coverage')

    def test_invalid_input_and_nonfinite_predictions(self):
        response = self.client.post('/api/routing/event',json={'scenario_id':self.scenario_id,'lat':91,'lng':0})
        self.assertEqual(response.status_code,422)
        self.save_model()
        with patch('backend.services.routing_service.predict',side_effect=lambda model,features:[float('nan')]*len(features)):
            self.assertEqual(self.request(policy='predictive')['code'],'invalid_prediction')

    def test_context_lists_models_only_for_their_own_scenario(self):
        experiment_id = self.save_model()
        data = self.client.get('/api/routing/context').json()['data']
        self.assertEqual(data['models'][0]['experiment_id'],experiment_id)
        self.assertEqual(data['models'][0]['scenario_id'],self.scenario_id)
        result = self.request(scenario_id=self.other_id, policy='predictive',
                              access_radius_km=10, experiment_id=experiment_id)
        self.assertEqual(result['code'],'no_model')

    def test_application_estimate_includes_access_even_with_no_backbone_hops(self):
        result = self.request(lng=.2, target_id='G1', service='Gaming')
        route = result['route']
        self.assertEqual(route['hop_count'], 0)
        self.assertGreater(route['total_static_transfer_ms'], 0)
        self.assertAlmostEqual(route['total_static_transfer_ms'], route['access_rtt_ms'])
        application = route['application']
        self.assertAlmostEqual(application['estimated_one_way_ms'], 1 + 256 * 8 / (100 * 1000))
        self.assertTrue(application['latency_budget_met'])

    def test_reuses_pending_network_job_even_when_a_newer_other_task_exists(self):
        with self.session() as db:
            pending = Experiment(scenario_id=self.scenario_id, algorithm='Predictive', status='QUEUED',
                                 rounds=10, learning_rate=.01, config_json={'task':'network_delay'})
            db.add(pending); db.flush()
            job_id = pending.id
            db.add(Experiment(scenario_id=self.scenario_id, algorithm='Predictive', status='QUEUED',
                              rounds=10, learning_rate=.01, config_json={'task':'mnist'}))
            db.commit()
        result = self.request(policy='predictive', auto_train=True)
        self.assertEqual(result['code'], 'training')
        self.assertEqual(result['training']['experiment_id'], job_id)

    def test_missing_model_does_not_generate_training_data_by_default(self):
        result = self.request(policy='predictive')
        self.assertEqual(result['code'], 'no_model')
        with self.session() as db:
            self.assertEqual(db.query(Experiment).count(), 0)
            from backend.models.network_learning import NetworkDataset
            self.assertEqual(db.query(NetworkDataset).count(), 0)

    def test_load_reduction_is_explicit_and_both_routes_share_applied_load(self):
        with self.session() as db:
            db.query(Node).update({'bandwidth': 6})
            db.query(NetworkLink).update({'bandwidth': 6})
            db.commit()
        self.assertEqual(self.request(service='Watch Video', load_ratio=.8)['code'], 'no_path')
        result = self.request(service='Watch Video', load_ratio=.8, allow_load_reduction=True)
        self.assertTrue(result['load_reduced'])
        self.assertEqual(result['requested_load_ratio'], .8)
        self.assertLess(result['applied_load_ratio'], .8)
        self.assertGreaterEqual(result['route']['bottleneck'], 5)
        self.assertEqual(result['route']['application'], result['baseline']['application'])

    def test_totals_compare_access_when_model_selects_another_ingress(self):
        self.save_model()
        result = self.request(policy='predictive', access_radius_km=100)
        for route in (result['route'], result['baseline']):
            self.assertAlmostEqual(route['total_predicted_transfer_ms'], route['predicted_access_rtt_ms'] + route['predicted_transfer_ms'])
        self.assertAlmostEqual(result['comparison']['predicted_cost_change'],
                               result['baseline']['total_predicted_transfer_ms'] - result['route']['total_predicted_transfer_ms'])

    def test_default_global_access_routes_from_remote_poles_and_dateline(self):
        for lat, lng in [(80, 100), (-90, -180), (90, 180), (0, 180)]:
            with self.subTest(lat=lat, lng=lng):
                result = self.request(lat=lat, lng=lng, access_radius_km=None)
                self.assertEqual(result['status'], 'routed')
                self.assertEqual(result['access_search']['mode'], 'global')
                self.assertIsNone(result['access_search']['used_radius_km'])
                self.assertGreater(result['route']['accessDistanceKm'], 5000)
                self.assertTrue(result['route']['access']['virtual'])
                self.assertNotIn('FOREIGN', result['route']['path'])
        response = self.client.post('/api/routing/event', json={
            'scenario_id': self.scenario_id, 'lat': 80, 'lng': 100, 'policy': 'static'})
        self.assertEqual(response.json()['data']['status'], 'routed')

    def test_explicit_radius_is_respected_even_for_remote_adaptive_access(self):
        self.assertEqual(self.request(lat=80, lng=100, topology='adaptive', access_radius_km=10)['code'], 'no_coverage')

    def test_model_changes_global_ingress_even_without_backbone_links(self):
        self.save_model()
        with self.session() as db:
            db.get(Node, 'A').status = 'OFFLINE'
            db.get(Node, 'B').status = 'OFFLINE'
            db.query(NetworkLink).delete()
            db.commit()
        with patch('backend.services.routing_service.predict', side_effect=lambda model, features: [
            10000 if f['distance_km'] < 30 else 1 for f in features
        ]) as inference:
            result = self.request(policy='predictive', access_radius_km=None)
        self.assertEqual(inference.call_count, 1)
        self.assertEqual(len(inference.call_args.args[1]), 2)
        self.assertEqual(result['baseline']['path'], ['G1'])
        self.assertEqual(result['route']['path'], ['G2'])
        self.assertEqual(result['route']['total_predicted_transfer_ms'], 1)
        for route in (result['route'], result['baseline']):
            score = route['score_breakdown']
            self.assertAlmostEqual(score['total'], sum(score[k] for k in ('delay', 'capacity', 'distance', 'preference')))

    def test_global_access_still_respects_elevated_horizon_and_custom_demand(self):
        with self.session() as db:
            db.get(Node, 'A').type = 'SPACE'
            db.get(Node, 'A').alt = 550
            db.get(Node, 'A').lng = 180
            db.get(Node, 'G1').bandwidth = 10
            db.commit()
        result = self.request(access_radius_km=None, required_bandwidth_mbps=20)
        self.assertEqual(result['route']['path'], ['G2'])
        self.assertEqual(result['profile']['min_bandwidth'], 20)
        self.assertEqual(result['route']['application']['required_bandwidth_mbps'], 20)
        self.assertGreaterEqual(result['route']['bottleneck'], 20)
        self.assertNotIn('A', result['route']['path'])
        self.assertEqual(self.request(access_radius_km=None, required_bandwidth_mbps=1000)['code'], 'no_path')

    def test_equal_predictions_are_ranked_by_distance_and_bandwidth(self):
        self.save_model()
        with self.session() as db:
            db.get(Node, 'A').status = 'OFFLINE'
            db.get(Node, 'B').status = 'OFFLINE'
            db.commit()
        with patch('backend.services.routing_service.predict', side_effect=lambda model, features: [10] * len(features)):
            result = self.request(policy='predictive', access_radius_km=None)
            self.assertEqual(result['route']['path'], ['G1'])
            with self.session() as db:
                db.get(Node, 'G1').bandwidth = .1
                db.commit()
            result = self.request(policy='predictive', access_radius_km=None)
            self.assertEqual(result['route']['path'], ['G2'])

    def test_invalid_custom_demand_and_radius_are_rejected(self):
        for params in [{'required_bandwidth_mbps': 0}, {'required_bandwidth_mbps': -1},
                       {'access_radius_km': 0}, {'access_radius_km': 30000}]:
            response = self.client.post('/api/routing/event', json={
                'scenario_id': self.scenario_id, 'lat': 0, 'lng': 0, **params})
            self.assertEqual(response.status_code, 422)

    def add_satellites(self):
        with self.session() as db:
            for index in range(8):
                db.add(Node(id=f'S{index}',type='SPACE',lat=0,lng=1+index*.1,alt=550,
                            bandwidth=100,latency=1,status='ACTIVE',scenario_id=self.scenario_id))
            db.commit()

    def test_remote_mobility_uses_a_connected_satellite_chain_without_db_writes(self):
        self.add_satellites()
        result=self.request(lng=100,topology='adaptive',access_radius_km=None,allow_reposition=True)
        self.assertEqual(result['status'],'routed')
        self.assertTrue(result['mobility']['required'])
        self.assertGreaterEqual(len(result['mobility']['moves']),2)
        self.assertFalse(result['route']['access']['virtual'])
        self.assertIn(result['route']['positions'][0]['type'],['SPACE','AIR','SEA'])
        from backend.services.routing_service import visible
        from types import SimpleNamespace
        positions=result['route']['positions']
        self.assertTrue(visible(SimpleNamespace(lat=0,lng=100,alt=0),SimpleNamespace(**positions[0])))
        for first,second in zip(positions,positions[1:]):
            self.assertTrue(visible(SimpleNamespace(**first),SimpleNamespace(**second)))
        with self.session() as db:
            for move in result['mobility']['moves']:
                self.assertEqual(db.get(Node,move['node_id']).lng,move['from']['lng'])
        boosted=self.request(lng=100,topology='adaptive',access_radius_km=None,allow_reposition=True,mobility_boost=4)
        self.assertAlmostEqual(result['mobility']['eta_s']/2,boosted['mobility']['eta_s'],places=5)

    def test_remote_mobility_reuses_fl_checkpoint_to_score_future_links(self):
        self.add_satellites()
        experiment=self.save_model()
        result=self.request(lng=100,topology='adaptive',access_radius_km=None,allow_reposition=True,policy='predictive')
        self.assertEqual(result['status'],'routed')
        self.assertEqual(result['model']['experiment_id'],experiment)
        self.assertGreater(len(result['mobility']['moves']),0)
        self.assertTrue(all(hop['predicted_ms'] is not None for hop in result['route']['hops']))
        self.assertAlmostEqual(result['mobility']['score_s'],result['mobility']['eta_s']+result['route']['cost']/1000)

    def test_mobility_requires_resources_and_does_not_make_virtual_ground_access(self):
        with self.session() as db:
            db.get(Node,'A').status='OFFLINE'; db.get(Node,'B').status='OFFLINE'; db.commit()
        result=self.request(lng=150,topology='adaptive',access_radius_km=None,allow_reposition=True)
        self.assertEqual(result['code'],'mobility_unavailable')
        self.assertIsNone(result['route'])

    def test_remote_mobility_preserves_invalid_prediction_error(self):
        self.add_satellites()
        self.save_model()
        with patch('backend.services.routing_service.predict', side_effect=lambda model, features: [float('nan')] * len(features)) as inference:
            result=self.request(lng=100,topology='adaptive',access_radius_km=None,allow_reposition=True,policy='predictive')
        self.assertEqual(result['code'],'invalid_prediction')
        self.assertEqual(inference.call_count,1)
        self.assertIn('mobility_preview',result)

    def test_a_ship_can_reposition_faster_than_a_far_satellite(self):
        with self.session() as db:
            db.get(Node,'A').lng=4.501
            db.get(Node,'B').status='OFFLINE'
            db.get(Node,'G1').lng=0
            db.get(Node,'G2').status='OFFLINE'
            db.add(Node(id='SAT-FAR',type='SPACE',lat=0,lng=180,alt=550,bandwidth=100,latency=1,status='ACTIVE',scenario_id=self.scenario_id))
            db.commit()
        result=self.request(lng=6,topology='adaptive',access_radius_km=None,allow_reposition=True)
        self.assertEqual(result['status'],'routed')
        self.assertEqual(result['mobility']['moves'][0]['type'],'SEA')

    def test_a_uav_can_reposition_faster_than_a_far_satellite(self):
        with self.session() as db:
            db.get(Node,'A').status='OFFLINE'
            db.get(Node,'B').lng=1.5; db.get(Node,'B').alt=.3
            db.get(Node,'G1').lng=0
            db.get(Node,'G2').status='OFFLINE'
            db.add(Node(id='SAT-FAR',type='SPACE',lat=0,lng=180,alt=550,bandwidth=100,latency=1,status='ACTIVE',scenario_id=self.scenario_id))
            db.commit()
        result=self.request(lng=.8,topology='adaptive',access_radius_km=None,allow_reposition=True)
        self.assertEqual(result['status'],'routed')
        self.assertEqual(result['mobility']['moves'][0]['type'],'AIR')

    def test_background_topology_is_scoped_active_and_bounded(self):
        with self.session() as db:
            db.get(Node,'B').status='OFFLINE'; db.commit()
        response=self.client.get(f'/api/routing/topology?scenario_id={self.scenario_id}&topology=adaptive')
        self.assertEqual(response.status_code,200)
        graph=response.json()['data']
        ids={node['id'] for node in graph['nodes']}
        self.assertNotIn('FOREIGN',ids); self.assertNotIn('B',ids)
        self.assertTrue(all(link['source'] in ids and link['target'] in ids for link in graph['links']))
        self.assertLessEqual(len(graph['links']),3*len(ids))

    def test_nearby_generator_rejects_links_below_elevated_horizon(self):
        with self.session() as db:
            db.query(NetworkLink).delete()
            db.get(Node,'B').lng=10
            db.get(Node,'B').alt=.3
            db.commit()
        response=self.client.post(f'/api/links/generate-nearby?scenario_id={self.scenario_id}&max_distance_km=5000&neighbors_per_node=5')
        self.assertEqual(response.status_code,200)
        self.assertTrue(all('B' not in (link['source'],link['target']) for link in response.json()['data']['links']))


if __name__ == '__main__':
    unittest.main()
