"""Unified original API and global shared-link behavior."""
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend.database.database import Base,get_db
from backend.main import app
from backend.models.scenario import Scenario
from backend.models.network import Node,NetworkLink
from backend.models.network_learning import NetworkDataset,NetworkObservation,NetworkClock
from backend.models.routing_event import RoutingEvent
from backend.services.fluid_network_service import advance

class UnifiedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(bind=self.engine)
        with self.sessions() as db:
            scenario=Scenario(name='Global snapshot fixture',total_nodes=4)
            db.add(scenario);db.flush();self.sid=scenario.id
            for i,layer in enumerate(('GROUND','AIR','SPACE','SEA')):
                db.add(Node(id=f'N{i}',type=layer,lat=0,lng=i*.01,alt=550 if layer=='SPACE' else .1,
                    bandwidth=100,latency=1,status='ACTIVE',scenario_id=self.sid))
            db.flush()
            for i in range(3):db.add(NetworkLink(source=f'N{i}',target=f'N{i+1}',bandwidth=10,latency=2,distance=1,status='ACTIVE'))
            db.commit()
        def dependency():
            with self.sessions() as db:yield db
        app.dependency_overrides[get_db]=dependency
        self.client=TestClient(app)
    def tearDown(self):
        app.dependency_overrides.pop(get_db,None);self.engine.dispose()
    def test_original_api_defaults_to_http_and_keeps_scenario_topology(self):
        with patch('backend.routers.federated_learning.run_experiment'):
            response=self.client.post('/api/fl/experiments',json=dict(task='network_delay',scenario_id=self.sid,
                pool_mode='all',client_count=4,samples_per_client=80,rounds=1))
        self.assertEqual(response.status_code,202,response.text)
        run=self.client.get('/api/fl/experiments/'+str(response.json()['data']['id'])).json()['data']
        self.assertEqual(run['config']['runtime'],'federated-http-v3')
        self.assertEqual(len(run['config']['distributed_config']['topology']['nodes']),4)
        self.assertEqual(run['config']['candidate_pool'],['N0','N1','N2','N3'])
        with self.sessions() as db:self.assertEqual(db.query(NetworkObservation).count(),0)
        raw=self.client.get(f"/api/fl/datasets/{run['dataset_id']}/observations")
        self.assertEqual(raw.status_code,403)
    def test_no_separate_application_or_navigation(self):
        page=self.client.get('/').text
        self.assertNotIn('/distributed/',page)
        self.assertEqual(self.client.get('/distributed/').status_code,404)
        self.assertEqual(self.client.post('/api/fl/experiments',json={},headers={'Origin':'https://untrusted.example'}).status_code,403)
    def test_shared_link_allocator_services_original_saved_events(self):
        with self.sessions() as db:
            link=db.query(NetworkLink).filter_by(source='N0',target='N1').one()
            clock=NetworkClock(scenario_id=self.sid,sim_time_s=0);db.add(clock)
            for i in range(2):
                result=dict(runtime='federated-http-v3',allocation_policy='equal',profile={'min_bandwidth':1},
                    route=dict(path=['N0','N1'],hops=[dict(link_id=link.id,source='N0',target='N1',bandwidth_mbps=10)],sourceCapacityMbps=100),
                    flow=dict(engine='shared-fluid-v3',state='transmitting',remaining_mbit=100,total_mbit=100,
                        delivered_mbit=0,deadline_s=100,last_route_s=0,reroutes=0,history=[]))
                db.add(RoutingEvent(client_key=str(i),display_number=i+1,scenario_id=self.sid,lat=0,lng=0,service='Message',config_json={},result_json=result))
            db.commit();advance(db,clock,1);db.commit()
            flows=[e.result_json['flow'] for e in db.query(RoutingEvent)]
            self.assertAlmostEqual(sum(f['allocated_mbps'] for f in flows),10)
            self.assertTrue(all(f['remaining_mbit']==95 for f in flows))
            link.status='INACTIVE';db.commit()
            advance(db,clock,1);db.commit()
            flows=[e.result_json['flow'] for e in db.query(RoutingEvent)]
            self.assertTrue(all(f['allocated_mbps']==0 and f['remaining_mbit']==95 for f in flows))

if __name__=='__main__':unittest.main()
