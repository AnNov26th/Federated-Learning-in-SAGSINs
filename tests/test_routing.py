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
                                                             'policy':'static','load_ratio':0, **kwargs})
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
        self.assertEqual(self.request(policy='predictive')['code'],'no_model')
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
        result = self.request(scenario_id=self.other_id,policy='predictive')
        self.assertEqual(result['code'],'no_target')


if __name__ == '__main__':
    unittest.main()
