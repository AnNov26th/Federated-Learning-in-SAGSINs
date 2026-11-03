import copy,math,unittest
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.database.database import Base
from backend.models.network import Node,NetworkLink
from backend.models.scenario import Scenario
from backend.models.network_learning import NetworkClock
from backend.services.network_motion_service import position_at,snapshot
from backend.services.service_routing_service import build_frame,access,route,refresh_route,accept_change
from backend.services.service_routing_service import frame_for


class SharedMotionTests(unittest.TestCase):
    def test_motion_is_deterministic_and_preserves_inventory(self):
        node=Node(id='SAT',type='SPACE',lat=0,lng=0,alt=550,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1)
        initial=position_at(node,0)
        self.assertAlmostEqual(initial['lat'],0);self.assertAlmostEqual(initial['lng'],0)
        self.assertEqual(position_at(node,100),position_at(node,100))
        self.assertNotEqual(position_at(node,100),initial)
        self.assertEqual((node.lat,node.lng),(0,0))
        self.assertEqual(position_at(node,100)['alt'],550)

    def test_repeated_observers_do_not_advance_clock(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Scenario(id=1,name='clock'));db.add(NetworkClock(scenario_id=1,sim_time_s=123));db.commit()
            a=snapshot(db,1);b=snapshot(db,1)
            self.assertEqual(a,b);self.assertEqual(db.get(NetworkClock,1).sim_time_s,123)
        engine.dispose()

    def test_satellite_leaving_horizon_removes_access_and_contact(self):
        sat=Node(id='SAT',type='SPACE',lat=0,lng=0,alt=550,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1)
        ground=Node(id='G',type='GROUND',lat=0,lng=0,alt=0,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1)
        client=SimpleNamespace(lat=0,lng=0,device='satellite_terminal')
        first=build_frame([sat,ground],[],0)
        self.assertIn('SAT',access(first,client,'Video Call'))
        period=2*math.pi*math.sqrt(6921**3/398600.4418)
        later=build_frame([sat,ground],[],period/2)
        self.assertFalse(access(later,client,'Video Call'))
        self.assertNotIn(('SAT','G'),later['edges'])

    def test_inactive_saved_contact_is_not_implicitly_reactivated(self):
        a=Node(id='SAT',type='SPACE',lat=0,lng=0,alt=550,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1)
        b=Node(id='G',type='GROUND',lat=0,lng=0,alt=0,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1)
        frame=build_frame([a,b],[NetworkLink(id=1,source='SAT',target='G',status='INACTIVE',bandwidth=10,latency=1)],0)
        self.assertFalse(frame['edges'])

    def test_selecting_a_different_model_does_not_change_live_telemetry(self):
        from sagsin.model import DelayModel,envelope
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        checkpoint=envelope(DelayModel('trend'))
        candidates=[(SimpleNamespace(id=i,config_json={'distributed_config':{'seed':i}}),None,
                     SimpleNamespace(checkpoint_json=checkpoint),SimpleNamespace(config_json={'runtime':'federated-http-v3'})) for i in (11,42)]
        with Session(engine) as db:
            db.add(Scenario(id=1,name='model independent weather'))
            db.add_all([Node(id='S',scenario_id=1,type='SPACE',lat=0,lng=0,alt=550,bandwidth=20,latency=1,status='ACTIVE'),
                        Node(id='G',scenario_id=1,type='GROUND',lat=0,lng=0,alt=0,bandwidth=20,latency=1,status='ACTIVE')]);db.commit()
            with patch('backend.services.routing_service.model_candidates',return_value=candidates),patch('backend.services.routing_service.model_summary',side_effect=lambda c:{'experiment_id':c[0].id}):
                a=frame_for(db,1,11);b=frame_for(db,1,42)
            self.assertEqual(a['config'],b['config'])
            self.assertEqual([e['current_ms'] for e in a['edges'].values()],[e['current_ms'] for e in b['edges'].values()])
        engine.dispose()


class QoSRoutingTests(unittest.TestCase):
    def fixture(self):
        nodes={key:SimpleNamespace(id=key,type='GROUND',lat=0,lng=lng,alt=0,bandwidth=20,latency=1,status='ACTIVE',scenario_id=1) for key,lng in [('A',0),('B',5),('D',10)]}
        edges={}
        def add(a,b,delay,length,static=None):
            edges[(a,b)]=dict(source=a,target=b,link_id=a+b,bandwidth_mbps=10,current_ms=delay,static_ms=delay if static is None else static,predicted_ms=delay,features={'distance_km':length},estimated=False)
        add('A','D',200,1100,10);add('A','B',40,550);add('B','D',40,550)
        return dict(nodes=nodes,edges=edges,now=0,model=None),SimpleNamespace(lat=0,lng=0,device='network_gateway'),SimpleNamespace(lat=0,lng=10,device='network_gateway')

    def test_qos_feasible_alternative_beats_cheaper_over_budget_path(self):
        frame,a,b=self.fixture()
        result,_=route(frame,a,b,'Video Call','static')
        self.assertEqual(result['path'],['A','B','D'])
        self.assertTrue(result['application']['latency_budget_met'])

    def test_distance_bound_rejects_absurd_detour(self):
        frame,a,b=self.fixture();del frame['edges'][('A','D')]
        for edge in frame['edges'].values():edge['features']['distance_km']=10000
        result,_=route(frame,a,b,'Video Call','current')
        self.assertIsNone(result)

    def test_hysteresis_hold_and_improvement(self):
        old=[dict(path=['A','D'],score=100,application={'latency_budget_met':True})]
        new=[dict(path=['A','B','D'],score=80,application={'latency_budget_met':True})]
        self.assertFalse(accept_change(old,new,5,0)[0])
        self.assertTrue(accept_change(old,new,11,0)[0])
        new[0]['score']=90;self.assertFalse(accept_change(old,new,11,0)[0])
        self.assertTrue(accept_change([],new,1,0)[0])
        new[0]['application']['latency_budget_met']=False
        self.assertFalse(accept_change(old,new,100,0)[0])

    def test_future_geometry_is_not_available_in_current_frame(self):
        frame,a,b=self.fixture();before=copy.deepcopy(frame)
        route(frame,a,b,'Video Call','current')
        self.assertEqual(frame,before)


if __name__=='__main__':unittest.main()
