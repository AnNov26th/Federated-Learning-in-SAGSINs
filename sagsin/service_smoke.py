"""Exercise real HTTP/WebSocket service sessions on the largest saved scenario.

Creates (or reuses) two named demo clients and retains finished sessions as evidence.
Does not alter topology, training nodes, or existing service sessions.
"""
import argparse
import asyncio
import json
import math
import time
import urllib.request
from datetime import datetime,timezone
import websockets
from sagsin.paths import OUTPUT
from sagsin.storage import write_json


async def run(url):
    def api(path,body=None):
        request=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,
                                       headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    nodes=api('/api/nodes')['data']
    counts={}
    for node in nodes:counts[node['scenario_id']]=counts.get(node['scenario_id'],0)+1
    scenario=max(counts,key=counts.get)
    ground=[node for node in nodes if node['scenario_id']==scenario and node['type']=='GROUND' and node['status']=='ACTIVE']
    def xyz(node):
        lat,lng=math.radians(node['lat']),math.radians(node['lng'])
        return (math.cos(lat)*math.cos(lng),math.sin(lat),math.cos(lat)*math.sin(lng))
    pairs=[(sum((x-y)**2 for x,y in zip(xyz(a),xyz(b))),a,b) for a in ground for b in ground if a['lat']*b['lat']<0]
    _,north,south=max(pairs,key=lambda pair:pair[0])
    created=[]
    existing=api(f'/api/service/state?scenario_id={scenario}')['clients']
    for name,node in [('A',north),('B',south)]:
        reused=next((c for c in existing if c['name']==f'Demo liên bán cầu {name}' and c['device']=='network_gateway'
                     and abs(c['lat']-node['lat'])<1e-4 and abs(c['lng']-node['lng'])<1e-4),None)
        created.append(reused or api('/api/service/clients',dict(scenario_id=scenario,name=f'Demo liên bán cầu {name}',
            lat=node['lat'],lng=node['lng'],device='network_gateway')))
    websocket_url=url.replace('http://','ws://').replace('https://','wss://')
    async with websockets.connect(f"{websocket_url}/api/service/clients/{created[0]['id']}/ws") as caller, \
               websockets.connect(f"{websocket_url}/api/service/clients/{created[1]['id']}/ws") as callee:
        for socket,client in zip((caller,callee),created):
            await socket.send(json.dumps(dict(type='register',token=client['token'])))
            await socket.recv()
        async def command(socket,kind,**fields):
            identifier=str(time.time_ns())
            await socket.send(json.dumps(dict(type=kind,request_id=identifier,**fields)))
            while True:
                value=json.loads(await asyncio.wait_for(socket.recv(),15))
                if value.get('request_id')==identifier:
                    if value['type']=='error':raise RuntimeError(value['message'])
                    return value
        async def until(identifier,states,timeout=45):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                value=await command(caller,'heartbeat');await command(callee,'heartbeat')
                session=next(s for s in value['sessions'] if s['id']==identifier)
                if session['state'] in states:return session
                if session['state']=='failed':raise AssertionError(session['result']['reason'])
                await asyncio.sleep(1)
            raise TimeoutError(f'Session #{identifier} did not reach {states}')
        response=await command(caller,'start',request=dict(service='Video Call',target_id=created[1]['id'],policy='static'))
        identifier=response['session_id']
        try:
            await command(callee,'accept',session_id=identifier)
            active=await until(identifier,{'active'})
            assert len(active['result']['rates_mbps'])==2 and min(active['result']['rates_mbps'])>0
            first_delivered=active['result']['delivered_mbit']
            await asyncio.sleep(5)
            sustained=await until(identifier,{'active'})
            assert sustained['result']['delivered_mbit']>first_delivered
        finally:
            await command(caller,'end',session_id=identifier)
        ended=await until(identifier,{'ended'})
        assert not ended['result']['rates_mbps'] and ended['result']['routes']
        emergency_id=(await command(caller,'start',request=dict(service='Emergency',policy='static')))['session_id']
        try:
            emergency=await until(emergency_id,{'completed'})
            assert emergency['result'].get('acknowledged') and not emergency['result']['rates_mbps']
        finally:
            # Idempotent on completion; avoids leaving a live session on failure.
            await command(caller,'end',session_id=emergency_id)
        assert len(api('/api/nodes')['data'])==len(nodes)
        evidence=dict(at=datetime.now(timezone.utc).isoformat(),scenario_id=scenario,
            nodes_unchanged=len(nodes),clients=[{k:v for k,v in client.items() if k!='token'} for client in created],
            call_active=active,call_sustained=sustained,call_ended=ended,emergency=emergency)
        write_json(OUTPUT/'acceptance'/'service-sessions.json',evidence)
        print(json.dumps(dict(scenario=scenario,client_ids=[c['id'] for c in created],call_id=identifier,
            call_rates_mbps=active['result']['rates_mbps'],call_ended=ended['state'],
            emergency_id=emergency_id,emergency_ack=emergency['result']['acknowledged'],nodes_unchanged=len(nodes)),indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:8000')
    asyncio.run(run(parser.parse_args().url.rstrip('/')))


if __name__=='__main__':main()
