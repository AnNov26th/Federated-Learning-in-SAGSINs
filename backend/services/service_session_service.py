"""Persistent simulated service sessions, driven by the shared backend clock."""
from copy import deepcopy
from types import SimpleNamespace
import time
from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified
from backend.models.service_session import ServiceClient, ServiceSession
from backend.models.network import Node
from backend.schemas.routing import EventRouteRequest
from backend.services.event_device_service import resolve_event, device_access_limit, elevation_deg
from backend.services.routing_service import visible, channel_distance, surface_distance, ACCESS_LIMITS_KM, SERVICES
from backend.services import service_routing_service as dynamic_routing

TERMINAL = {'completed', 'ended', 'rejected', 'failed'}
LEASE_S = 35


def online(client):
    return client is not None and not client.deleted and time.time() - client.last_seen <= LEASE_S


def client_view(client):
    return {key: getattr(client, key) for key in ('id', 'scenario_id', 'name', 'lat', 'lng', 'device', 'token')} | {'online': online(client)}


def session_view(session):
    return {key: getattr(session, key) for key in ('id', 'scenario_id', 'source_id', 'target_id', 'service', 'state')} | {
        'config': session.config_json, 'result': session.result_json}


def create_session(db, client, request):
    from backend.services.fluid_network_service import clock_for
    if not online(client):
        raise HTTPException(409, 'Client chưa kết nối. Hãy chờ WebSocket đăng ký.')
    peer_service = request.service in {'Video Call', 'Gaming', 'Message'}
    target = db.get(ServiceClient, request.target_id) if request.target_id else None
    if peer_service and (not target or target.id == client.id or target.scenario_id != client.scenario_id):
        raise HTTPException(422, 'Chọn một client khác trong cùng scenario.')
    if not peer_service and request.target_id:
        raise HTTPException(422, 'Dịch vụ này dùng máy chủ GROUND, không chọn client đích.')
    if target and not online(target):
        raise HTTPException(409, 'Client đích đang ngoại tuyến.')
    now = clock_for(db, client.scenario_id).sim_time_s
    session = ServiceSession(scenario_id=client.scenario_id, source_id=client.id,
        target_id=request.target_id, service=request.service,
        state='ringing' if request.service in {'Video Call', 'Gaming'} else 'connecting',
        config_json=request.model_dump(), result_json=dict(created_s=now, last_progress_s=now,
            routes=[], rates_mbps=[], delivered_mbit=0., remaining_mbit=.008192 if request.service == 'Emergency' else .032768,
            phase='data', history=[], reason='Chờ bên nhận chấp nhận' if request.service in {'Video Call','Gaming'} else 'Đang tìm tuyến'))
    db.add(session); db.flush()
    return session


def action(db, client, session, command):
    from backend.services.fluid_network_service import clock_for
    if client.id not in {session.source_id, session.target_id}:
        raise HTTPException(403, 'Client không thuộc phiên này.')
    if session.state in TERMINAL:
        return session
    if command in {'accept', 'reject'}:
        if client.id != session.target_id or session.state != 'ringing':
            raise HTTPException(409, 'Chỉ bên nhận có thể nhận/từ chối cuộc gọi đang đổ chuông.')
        session.state = 'connecting' if command == 'accept' else 'rejected'
    elif command == 'end':
        session.state = 'ended'
    else:
        raise HTTPException(422, 'Lệnh phiên không hợp lệ.')
    result = deepcopy(session.result_json)
    result.update(rates_mbps=[], last_progress_s=clock_for(db, session.scenario_id).sim_time_s,
                  reason={'accept':'Đã nhận cuộc gọi; đang tìm tuyến hai chiều', 'reject':'Bên nhận từ chối', 'end':'Chủ động kết thúc; đã giải phóng băng thông'}[command])
    session.result_json = result
    return session


def access_candidates(db, client, service):
    request = EventRouteRequest(scenario_id=client.scenario_id, lat=client.lat, lng=client.lng,
        source_device=client.device, service=service, routing_scope='global', policy='static')
    device = resolve_event(request)
    origin = SimpleNamespace(lat=client.lat, lng=client.lng, alt=0.)
    candidates = []
    for node in db.query(Node).filter_by(scenario_id=client.scenario_id, status='ACTIVE'):
        reach = device_access_limit(device, node.type)
        if reach == 0 or node.type not in ACCESS_LIMITS_KM:
            continue
        limit = min(ACCESS_LIMITS_KM[node.type], reach) if reach is not None else ACCESS_LIMITS_KM[node.type]
        distance = channel_distance(origin, node) if node.alt > 0 else surface_distance(origin, node)
        if distance > limit or not visible(origin, node):
            continue
        if node.type == 'SPACE' and device['device'] and elevation_deg(origin, node) < device['device'].get('min_elevation_deg', 0):
            continue
        capacity = min(node.bandwidth, device['device']['effective_bandwidth_mbps']) if device['device'] else node.bandwidth
        if capacity >= SERVICES[service]['min_bandwidth']:
            candidates.append((distance, node, capacity))
    return sorted(candidates, key=lambda item:(item[0], item[1].id))


def route_between(db, source, target, session, server_id=None):
    frame=dynamic_routing.frame_for(db,source.scenario_id,session.config_json.get('experiment_id'))
    return dynamic_routing.route(frame,source,target,session.service,session.config_json['policy'],server_id,
                                 session.config_json.get('max_path_stretch',2))


def reverse_route(route):
    value = deepcopy(route)
    value['path'].reverse(); value['positions'].reverse()
    value['hops'] = [{**hop, 'source':hop['target'], 'target':hop['source']} for hop in reversed(value['hops'])]
    value['sourceId'],value['targetId']=value['targetId'],value['sourceId']
    value['sourceCapacityMbps'],value['receiver_capacity_mbps']=value['receiver_capacity_mbps'],value['sourceCapacityMbps']
    return value


def prepare(db, clock, seconds, caps, legacy_nodes, legacy_links):
    """Append to the SAME allocation problem as existing saved routing flows."""
    now = clock.sim_time_s
    flows, contexts = [], []
    sessions = db.query(ServiceSession).filter_by(scenario_id=clock.scenario_id).order_by(ServiceSession.id).all()
    for session in sessions:
        if session.state in TERMINAL:
            continue
        result = deepcopy(session.result_json)
        result['rates_mbps'] = []
        source, target = db.get(ServiceClient, session.source_id), db.get(ServiceClient, session.target_id) if session.target_id else None
        timeout = session.config_json['wait_timeout_s']
        if session.state == 'ringing':
            if now-result['created_s'] >= timeout:
                session.state = 'failed'; result['reason'] = 'Không có phản hồi nhận cuộc gọi trong thời hạn.'
            session.result_json = result
            continue
        connected = online(source) and (not session.target_id or online(target))
        if not connected:
            session.state = 'interrupted'; result['reason'] = 'Client mất kết nối điều khiển; chờ nối lại.'
            if now-result['last_progress_s'] >= timeout:
                session.state = 'failed'; result['reason'] = 'Hết hạn mất liên lạc; đã trả tài nguyên. Chưa xác nhận hoàn tất.'
            session.result_json = result
            continue
        frame=dynamic_routing.frame_for(db,session.scenario_id,session.config_json.get('experiment_id'))
        if result['phase'] == 'ack_in_flight' and result.get('routes'):
            receipt_path=dynamic_routing.refresh_route(frame,reverse_route(result['routes'][0]),source,target,session.service,session.config_json['policy'],result.get('server_id'))
            if receipt_path is None:
                result.update(phase='ack',remaining_mbit=.000512,last_route_s=-100,route_available=False)
        if result['phase'] == 'ack_in_flight':
            session.state='confirming'
            result['reason']='ACK đã được gửi; đang truyền về client.'
            if now >= result['ack_arrives_s']:
                session.state='completed'
                result.update(acknowledged=True,acknowledged_s=now,reason='Đích đã xác nhận nhận đủ; đã giải phóng băng thông.')
            session.result_json=result
            continue
        if result['phase'] == 'server_processing' and now < result['ack_ready_s']:
            result['reason']='Dữ liệu đang tới đích.' if now < result['received_by_destination_s'] else 'Đích đã nhận dữ liệu; đang xử lý trước khi gửi ACK.'
            session.state = 'awaiting_ack'; session.result_json = result
            continue
        if result['phase'] == 'server_processing':
            result.update(phase='ack', remaining_mbit=.000512)
        reverse=result['phase']=='ack' or session.service=='Watch Video'
        old=result.get('routes',[])
        valid=[]
        for index,previous in enumerate(old):
            a,b=(target,source) if index==1 else (source,target)
            updated=dynamic_routing.refresh_route(frame,reverse_route(previous) if reverse else previous,a,b,session.service,session.config_json['policy'],result.get('server_id'),session.config_json.get('max_path_stretch',2))
            if updated:valid.append(reverse_route(updated) if reverse else updated)
        expected=2 if session.service in {'Video Call','Gaming'} else 1
        broken=len(valid)!=expected
        if broken:valid=[]
        refresh = broken or now-result.get('last_route_s', -100) >= session.config_json.get('reroute_interval_s',3)
        if refresh:
            forward, reason = route_between(db, source, target, session,result.get('server_id'))
            if session.service in {'Video Call','Gaming'} and forward:
                backward, reason = route_between(db, target, source, session)
                routes = [forward, backward] if backward else []
            elif forward:
                routes = [reverse_route(forward)] if result['phase'] == 'ack' or session.service == 'Watch Video' else [forward]
            else:
                routes = []
            if routes:
                if target is None and not result.get('server_id'):
                    result['server_id']=forward['targetId']
                accepted,why=dynamic_routing.accept_change(valid,routes,now,result.get('last_switch_s',-100),session.config_json.get('minimum_hold_s',10),session.config_json.get('reroute_improvement',.15))
                if accepted:
                    changed=bool(old) and [r['path'] for r in old]!=[r['path'] for r in routes]
                    if changed:result['reroutes']=result.get('reroutes',0)+1;result['handover_pause_s']=.1
                    result['last_switch_s']=now
                    result['route_audit']=(result.get('route_audit',[])+[dict(at_s=now,reason=why,paths=[r['path'] for r in routes])])[-30:]
                    valid=routes
                result['route_review']=why
            result.update(reason=reason,last_route_s=now)
        if valid:
            result['routes']=valid
            if session.config_json['policy']=='predictive' and not session.config_json.get('experiment_id') and frame['model']:
                session.config_json={**session.config_json,'experiment_id':frame['model']['experiment_id']}
        result['route_available']=bool(valid)
        result['motion_clock_s']=now
        if not result.get('route_available'):
            session.state = 'waiting'
            if now-result['last_progress_s'] >= timeout:
                session.state='failed'; result['reason']='Hết hạn chờ tuyến; chưa xác nhận hoàn tất.'
            session.result_json=result
            continue
        demand = SERVICES[session.service]['min_bandwidth']
        if result['phase'] == 'ack': demand=.05
        continuous = session.service in {'Video Call','Gaming','Watch Video'}
        identifiers=[]
        invalid=False
        for index, route in enumerate(result['routes']):
            resources=[]
            for key in route['path']:
                node=frame['nodes'].get(key)
                if not node or node.status!='ACTIVE': invalid=True; break
                resource='node:'+key
                capacity=max(0,node.bandwidth-legacy_nodes.get(key,0))
                caps[resource]=min(caps.get(resource,capacity),capacity);resources.append(resource)
            for hop in route['hops']:
                live=frame['edges'].get((hop['source'],hop['target']))
                if not live: invalid=True; break
                resource='link:'+str(hop['link_id'])
                capacity=max(0,live['bandwidth_mbps']-legacy_links.get(str(hop['link_id']),0))
                caps[resource]=min(caps.get(resource,capacity),capacity);resources.append(resource)
            for client in (source,target):
                if client is None: continue
                resource=f'client:{client.id}'
                device=resolve_event(EventRouteRequest(scenario_id=client.scenario_id,lat=client.lat,lng=client.lng,source_device=client.device,service=session.service))['device']
                capacity=device['effective_bandwidth_mbps'] if device else min(route['sourceCapacityMbps'],route['receiver_capacity_mbps'])
                caps[resource]=min(caps.get(resource,capacity),capacity);resources.append(resource)
            identifier=-(session.id*10+index+1)
            resource=f'service-demand:{identifier}';caps[resource]=demand;resources.append(resource)
            identifiers.append(identifier)
            flows.append(dict(id=identifier,path=list(dict.fromkeys(resources)),
                remaining_mbit=demand*seconds if continuous else result['remaining_mbit'],time_left_s=max(seconds,timeout-(now-result['last_progress_s']))))
        if invalid:
            flows=[flow for flow in flows if flow['id'] not in identifiers]
            result.update(route_available=False, rates_mbps=[], reason='Link hoặc node đã ngừng hoạt động; đang tìm lại tuyến.')
            session.state='waiting'
            if now-result['last_progress_s']>=timeout:session.state='failed'
        else:
            contexts.append((session,result,identifiers,continuous))
        session.result_json=result
        flag_modified(session,'result_json')
    return flows,contexts


def serve(contexts, rates, now, seconds):
    for session,result,identifiers,continuous in contexts:
        values=[rates[key] for key in identifiers]
        rate=min(values)
        # Both media directions advance at the smaller feasible rate.
        result['rates_mbps']=[rate]*len(values)
        if rate <= 1e-9:
            session.state='waiting';result['reason']='Chờ băng thông dùng chung.'
            if now-result['last_progress_s']>=session.config_json['wait_timeout_s']:
                session.state='failed';result['reason']='Hết hạn chờ băng thông; chưa hoàn tất.'
        else:
            session.state='active' if continuous else 'confirming' if result['phase']=='ack' else 'transmitting'
            result['quality']='degraded' if rate+1e-7 < SERVICES[session.service]['min_bandwidth'] or any(not route['application']['latency_budget_met'] for route in result['routes']) else 'within_demo_budget'
            window=max(0,seconds-result.pop('handover_pause_s',0))
            sent=rate*window if continuous else min(result['remaining_mbit'],rate*window)
            result['delivered_mbit']+=sent*len(values)
            result['last_progress_s']=now
            result['reason']='Đang truyền hai chiều' if len(values)==2 else 'Đang truyền xác nhận từ đích' if result['phase']=='ack' else 'Đang truyền'
            if not continuous:
                result['remaining_mbit']-=sent
                if result['remaining_mbit']<=1e-9:
                    result['rates_mbps']=[]
                    if result['phase']=='ack':
                        delay=max(route['application']['estimated_one_way_ms'] for route in result['routes'])/1000
                        session.state='confirming'
                        result.update(phase='ack_in_flight',ack_arrives_s=now+delay,reason='ACK đã được gửi; đang truyền về client.')
                    else:
                        delay=max(route['application']['estimated_one_way_ms'] for route in result['routes'])/1000
                        result.update(phase='server_processing',ack_ready_s=now+2+delay,received_by_destination_s=now+delay)
                        session.state='awaiting_ack';result['reason']='Đích đã nhận dữ liệu; chờ xử lý và truyền ACK về client.'
                        result['last_route_s']=-100
        result['history']=(result.get('history',[])+[dict(at_s=now,state=session.state,rates_mbps=result['rates_mbps'])])[-60:]
        session.result_json=result
        flag_modified(session,'result_json')
