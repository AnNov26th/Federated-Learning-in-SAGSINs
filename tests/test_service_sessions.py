import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.database.database import Base,get_db
from backend.main import app
from backend.models.scenario import Scenario
from backend.models.network import Node,NetworkLink
from backend.models.service_session import ServiceClient,ServiceSession
from backend.models.routing_event import RoutingEvent
from backend.models.participant import Participant
from backend.schemas.service_session import SessionCreate
from backend.services.service_session_service import create_session,action,TERMINAL
from backend.services.fluid_network_service import clock_for,advance


class ServiceSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(bind=self.engine)
        self.db=self.sessions()
        scenario=Scenario(name='Service test',total_nodes=2);self.db.add(scenario);self.db.flush();self.sid=scenario.id
        self.db.add_all([Node(id='NORTH',scenario_id=self.sid,type='GROUND',lat=10,lng=0,alt=0,bandwidth=20,latency=1,status='ACTIVE'),
                         Node(id='SOUTH',scenario_id=self.sid,type='GROUND',lat=-10,lng=160,alt=0,bandwidth=20,latency=1,status='ACTIVE')])
        self.db.flush()
        self.link=NetworkLink(source='NORTH',target='SOUTH',bandwidth=10,latency=60,distance=18000,status='ACTIVE');self.db.add(self.link)
        self.a=ServiceClient(name='A',scenario_id=self.sid,lat=10,lng=0,device='network_gateway',token='a',last_seen=time.time())
        self.b=ServiceClient(name='B',scenario_id=self.sid,lat=-10,lng=160,device='network_gateway',token='b',last_seen=time.time())
        self.db.add_all([self.a,self.b]);self.db.flush()
        self.clock=clock_for(self.db,self.sid);self.db.commit()
        self.before_nodes=self.db.query(Node).count();self.before_participants=self.db.query(Participant).count()

    def tearDown(self):
        app.dependency_overrides.pop(get_db,None);self.db.close();self.engine.dispose()

    def step(self,seconds=1):
        advance(self.db,self.clock,seconds);self.db.commit()

    def call(self):
        session=create_session(self.db,self.a,SessionCreate(service='Video Call',target_id=self.b.id))
        self.assertEqual(session.state,'ringing')
        action(self.db,self.b,session,'accept');self.db.commit()
        return session

    def test_cross_hemisphere_call_persists_until_hangup_and_never_adds_training_nodes(self):
        call=self.call()
        self.step()
        self.assertEqual(call.state,'active',call.result_json)
        self.assertEqual(len(call.result_json['rates_mbps']),2)
        self.assertEqual(call.result_json['routes'][0]['path'],['NORTH','SOUTH'])
        self.assertEqual(call.result_json['routes'][1]['path'],['SOUTH','NORTH'])
        self.step(120)
        self.assertEqual(call.state,'active')
        action(self.db,self.a,call,'end');self.db.commit();self.step()
        self.assertEqual(call.state,'ended');self.assertEqual(call.result_json['rates_mbps'],[])
        self.assertTrue(call.result_json['routes'])
        self.assertEqual(self.db.query(Node).count(),self.before_nodes)
        self.assertEqual(self.db.query(Participant).count(),self.before_participants)

    def test_emergency_requires_destination_ack_and_releases_while_processing(self):
        session=create_session(self.db,self.a,SessionCreate(service='Emergency'));self.db.commit()
        self.step()
        self.assertEqual(session.state,'awaiting_ack')
        self.assertEqual(session.result_json['rates_mbps'],[])
        self.assertFalse(session.result_json.get('acknowledged',False))
        self.step()
        self.assertNotEqual(session.state,'completed')
        for _ in range(6):self.step()
        self.assertEqual(session.state,'completed',session.result_json)
        self.assertTrue(session.result_json['acknowledged'])
        self.assertEqual(session.result_json['rates_mbps'],[])

    def test_ack_cannot_switch_to_another_server_if_original_server_fails(self):
        session=create_session(self.db,self.a,SessionCreate(service='Emergency',wait_timeout_s=5));self.db.commit();self.step()
        server=self.db.get(Node,session.result_json['server_id']);server.status='INACTIVE';self.db.commit()
        for _ in range(10):self.step()
        self.assertEqual(session.state,'failed')
        self.assertFalse(session.result_json.get('acknowledged',False))

    def test_no_coverage_does_not_invent_a_route(self):
        self.a.lat=70;self.a.lng=-90;self.a.device='smartphone'
        session=create_session(self.db,self.a,SessionCreate(service='Emergency',wait_timeout_s=5));self.db.commit()
        for _ in range(7):self.step()
        self.assertEqual(session.state,'failed')
        self.assertFalse(session.result_json['routes'])

    def test_predictive_without_checkpoint_never_silently_falls_back(self):
        session=create_session(self.db,self.a,SessionCreate(service='Video Call',target_id=self.b.id,policy='predictive',wait_timeout_s=5))
        action(self.db,self.b,session,'accept');self.db.commit();self.step()
        self.assertEqual(session.state,'waiting')
        self.assertIn('checkpoint',session.result_json['reason'])
        self.assertFalse(session.result_json['routes'])
        self.step(6);self.assertEqual(session.state,'failed')

    def test_link_failure_waits_and_reconnects_without_half_call(self):
        call=self.call();self.step();self.link.status='INACTIVE';self.db.commit();self.step()
        self.assertEqual(call.state,'waiting');self.assertEqual(call.result_json['rates_mbps'],[])
        self.link.status='ACTIVE';self.db.commit();self.step()
        self.assertEqual(call.state,'active')

    def test_offline_heartbeat_expires_session_without_marking_success(self):
        call=self.call();self.step()
        self.b.last_seen=time.time()-100;self.db.commit();self.step()
        self.assertEqual(call.state,'interrupted');self.assertEqual(call.result_json['rates_mbps'],[])
        self.step(40)
        self.assertEqual(call.state,'failed')

    def test_both_directions_share_link_capacity_with_other_calls(self):
        calls=[self.call() for _ in range(4)]
        self.step()
        allocated=sum(sum(c.result_json['rates_mbps']) for c in calls)
        self.assertLessEqual(allocated,10+1e-7)
        self.assertGreater(allocated,0)

    def test_new_call_and_old_flow_share_one_allocator(self):
        call=self.call()
        event=RoutingEvent(client_key='old-flow',display_number=1,scenario_id=self.sid,lat=10,lng=0,service='Message',config_json={},
            result_json=dict(runtime='federated-http-v3',profile={'min_bandwidth':1},
                route=dict(path=['NORTH','SOUTH'],sourceCapacityMbps=20,hops=[dict(link_id=self.link.id,source='NORTH',target='SOUTH',bandwidth_mbps=10)]),
                flow=dict(engine='shared-fluid-v3',state='transmitting',remaining_mbit=100,total_mbit=100,
                          delivered_mbit=0,deadline_s=100,last_route_s=0,reroutes=0,history=[])))
        self.db.add(event);self.db.commit();self.step()
        total=event.result_json['flow']['allocated_mbps']+sum(call.result_json['rates_mbps'])
        self.assertLessEqual(total,10+1e-7)
        self.assertGreater(event.result_json['flow']['allocated_mbps'],0)

    def test_receiver_range_is_checked_independently(self):
        self.b.device='smartphone';self.b.lat=-70;self.b.lng=-90;self.db.commit()
        call=self.call();self.step()
        self.assertEqual(call.state,'waiting')
        self.assertFalse(call.result_json['routes'])

    def test_same_access_node_still_allocates_both_device_directions(self):
        self.b.lat=self.a.lat;self.b.lng=self.a.lng;self.db.commit()
        call=self.call();self.step()
        self.assertEqual(call.state,'active')
        self.assertEqual(len(call.result_json['routes'][0]['hops']),0)
        self.assertEqual(call.result_json['rates_mbps'],[2,2])

    def test_only_callee_can_accept_and_other_clients_cannot_hangup(self):
        session=create_session(self.db,self.a,SessionCreate(service='Video Call',target_id=self.b.id))
        with self.assertRaises(HTTPException):action(self.db,self.a,session,'accept')
        stranger=ServiceClient(id=999)
        with self.assertRaises(HTTPException):action(self.db,stranger,session,'end')
        action(self.db,self.b,session,'reject');self.assertEqual(session.state,'rejected')

    def test_websocket_register_start_accept_and_hangup(self):
        def dependency():
            with self.sessions() as db:yield db
        app.dependency_overrides[get_db]=dependency
        browser=TestClient(app)
        with patch('backend.routers.service_sessions.SessionLocal',self.sessions):
            with browser.websocket_connect(f'/api/service/clients/{self.a.id}/ws') as caller:
                caller.send_json({'type':'register','token':'a'});self.assertEqual(caller.receive_json()['type'],'state')
                caller.send_json({'type':'start','request_id':'start1','request':{'service':'Video Call','target_id':self.b.id}})
                response=caller.receive_json();self.assertEqual(response['request_id'],'start1');identifier=response['session_id']
                with browser.websocket_connect(f'/api/service/clients/{self.b.id}/ws') as callee:
                    callee.send_json({'type':'register','token':'b'});callee.receive_json()
                    callee.send_json({'type':'accept','session_id':identifier});self.assertEqual(callee.receive_json()['sessions'][0]['state'],'connecting')
                caller.send_json({'type':'end','session_id':identifier});self.assertEqual(caller.receive_json()['sessions'][0]['state'],'ended')

    def test_websocket_rejects_invalid_token_and_cross_origin(self):
        browser=TestClient(app)
        from starlette.websockets import WebSocketDisconnect
        with patch('backend.routers.service_sessions.SessionLocal',self.sessions):
            with browser.websocket_connect(f'/api/service/clients/{self.a.id}/ws') as socket:
                socket.send_json({'type':'register','token':'wrong'})
                with self.assertRaises(WebSocketDisconnect):socket.receive_json()
            with self.assertRaises(WebSocketDisconnect):
                with browser.websocket_connect(f'/api/service/clients/{self.a.id}/ws',headers={'Origin':'https://wrong.example'}):pass

    def test_mysql_heartbeat_has_precision_for_short_leases(self):
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects.mysql import dialect
        self.assertIn('last_seen DOUBLE',str(CreateTable(ServiceClient.__table__).compile(dialect=dialect())))

    def test_delete_client_hides_routes_and_releases_active_call_but_keeps_audit(self):
        call=self.call();self.step()
        self.assertEqual(call.state,'active')
        def dependency():
            with self.sessions() as db:yield db
        app.dependency_overrides[get_db]=dependency
        browser=TestClient(app)
        response=browser.delete(f'/api/service/clients/{self.a.id}')
        self.assertEqual(response.status_code,200,response.text)
        self.db.expire_all()
        self.assertTrue(self.db.get(ServiceClient,self.a.id).deleted)
        self.assertEqual(call.state,'ended')
        self.assertEqual(call.result_json['rates_mbps'],[])
        self.assertTrue(call.result_json['routes'])
        state=browser.get(f'/api/service/state?scenario_id={self.sid}').json()
        self.assertEqual([c['id'] for c in state['clients']],[self.b.id])
        self.assertEqual(state['sessions'],[])
        self.step();self.assertEqual(call.result_json['rates_mbps'],[])
        self.assertEqual(self.db.query(Node).count(),self.before_nodes)
        self.assertEqual(browser.delete(f'/api/service/clients/{self.a.id}').status_code,200)
        with patch('backend.routers.service_sessions.SessionLocal',self.sessions):
            from backend.routers.service_sessions import command
            with self.assertRaises(HTTPException):command(self.a.id,'a',{'type':'register'})

    def test_delete_idle_client_is_hidden_without_affecting_other_client(self):
        from backend.routers.service_sessions import remove_client,snapshot
        remove_client(self.a.id,self.db)
        self.assertEqual([c['id'] for c in snapshot(self.db,self.sid)['clients']],[self.b.id])
        self.assertFalse(self.b.deleted)


if __name__=='__main__':unittest.main()
