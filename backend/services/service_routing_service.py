"""Shared dynamic contact graph and QoS-aware routing for service clients."""
import heapq
import math
from itertools import combinations
from types import SimpleNamespace
from backend.models.network import Node,NetworkLink
from backend.models.network_learning import NetworkClock
from backend.services.network_motion_service import moving_node
from backend.services.topology_service import feasible_pair
from backend.services.routing_service import (surface_distance,channel_distance,visible,SERVICES,APPLICATION_PROFILES,ACCESS_LIMITS_KM)
from backend.services.event_device_service import DEVICES,elevation_deg
from sagsin.topology import Link,channel
from sagsin.dataset import feature_row
from sagsin.model import predictions,validate_envelope


def distance(a,b):
    return surface_distance(a,b) if max(a.alt,b.alt)<=0 else channel_distance(a,b)


def build_frame(inventory,stored_links,now,config=None,model=None,summary=None):
    config=config or {'seed':42,'profile':'mixed'}
    active=[n for n in inventory if n.status=='ACTIVE' and n.type in ACCESS_LIMITS_KM and n.bandwidth>0 and all(math.isfinite(v) for v in (n.lat,n.lng,n.alt,n.bandwidth,n.latency))]
    nodes={n.id:moving_node(n,now) for n in active}
    previous={n.id:moving_node(n,now-1) for n in active}
    saved={frozenset((e.source,e.target)):e for e in stored_links if e.source in nodes and e.target in nodes}
    edges={};features=[];ordered=[]
    for a,b in combinations(nodes.values(),2):
        stored=saved.get(frozenset((a.id,b.id)))
        if stored and stored.status!='ACTIVE':continue
        # New contacts are radio opportunities; never invent terrestrial backhaul.
        if not stored and a.type==b.type=='GROUND':continue
        if not feasible_pair(a,b,allow_ground_backbone=stored is not None):continue
        identifier=stored.id if stored else 'contact:'+'|'.join(sorted((a.id,b.id)))
        capacity=min(a.bandwidth,b.bandwidth,stored.bandwidth if stored else math.inf)
        propagation=max(stored.latency if stored else 0,distance(a,b)/299.792458)
        edge=Link(f'A{identifier}' if stored else identifier,a.id,b.id,capacity,propagation,distance(a,b))
        if not channel(edge,int(now),config['seed'],config['profile'])['active']:continue
        pa,pb=previous[a.id],previous[b.id]
        old=Link(edge.id,a.id,b.id,capacity,max(stored.latency if stored else 0,distance(pa,pb)/299.792458),distance(pa,pb))
        for source,target in ((a,b),(b,a)):
            row=feature_row(edge,target.type,int(now),config['seed'],config['profile'],1200)
            before=feature_row(old,target.type,int(now)-1,config['seed'],config['profile'],1200)
            history=feasible_pair(pa,pb,stored is not None) and channel(old,int(now)-1,config['seed'],config['profile'])['active']
            row.update(previous_delay_ms=before['observed_delay_ms'] if history else row['observed_delay_ms'],history_valid=history)
            row['delta_delay_ms']=row['observed_delay_ms']-row['previous_delay_ms']
            if not history:row.update(load_before=row['load'],delta_load=0)
            hop=dict(link_id=identifier,source=source.id,target=target.id,bandwidth_mbps=row['available_mbps'],
                static_ms=propagation+1200*8/(capacity*1000),current_ms=row['observed_delay_ms'],predicted_ms=None,
                estimated=stored is None,features={**row,'latency_ms':propagation+row['queue_ms'],'bandwidth_mbps':row['available_mbps']})
            edges[(source.id,target.id)]=hop;ordered.append(hop);features.append(row)
    if model is not None and features:
        for edge,value in zip(ordered,predictions(model,features)):
            edge['predicted_ms']=max(.001,float(value))
    return dict(nodes=nodes,edges=edges,now=now,model=summary,config=config)


def frame_for(db,scenario_id,experiment_id=None):
    clock=db.get(NetworkClock,scenario_id);now=clock.sim_time_s if clock else 0
    key=('service_graph',scenario_id,now,experiment_id)
    if key in db.info:return db.info[key]
    from backend.services.routing_service import model_candidates,model_summary
    candidates=[c for c in model_candidates(db,scenario_id) if c[3].config_json.get('runtime')=='federated-http-v3']
    chosen=next((c for c in candidates if c[0].id==experiment_id),None) if experiment_id else next(iter(candidates),None)
    # Live weather/queues belong to the scenario, not to the chosen model.
    # Counterfactual benchmarks pass their paired seed/profile explicitly.
    config={'seed':42,'profile':'mixed'}
    model=validate_envelope(chosen[2].checkpoint_json) if chosen else None
    summary={k:v for k,v in model_summary(chosen).items() if k!='candidate_pool'} if chosen else None
    frame=build_frame(db.query(Node).filter_by(scenario_id=scenario_id).all(),db.query(NetworkLink).all(),now,config,model,summary)
    db.info[key]=frame
    return frame


def access(frame,client,service):
    origin=SimpleNamespace(lat=client.lat,lng=client.lng,alt=0.)
    device=DEVICES.get(client.device)
    demand=SERVICES[service]['min_bandwidth'];payload=APPLICATION_PROFILES[service]['payload_bytes']
    result={}
    for node in frame['nodes'].values():
        limit=min(ACCESS_LIMITS_KM[node.type],device['access_km'].get(node.type,0)) if device else ACCESS_LIMITS_KM[node.type]
        d=distance(origin,node)
        if not limit or d>limit or not visible(origin,node):continue
        if device and node.type=='SPACE' and elevation_deg(origin,node)<device.get('min_elevation_deg',0):continue
        capacity=min(node.bandwidth,device['uplink_mbps'],device['downlink_mbps']) if device else node.bandwidth
        if capacity<demand:continue
        delay=max(node.latency,d/299.792458)+payload*8/(capacity*1000)+(device['processing_ms'] if device else 0)
        result[node.id]=dict(distance=d,capacity=capacity,delay=delay)
    return result


def field(policy):return {'static':'static_ms','current':'current_ms','predictive':'predicted_ms'}[policy]


def make_route(frame,path,source_access,target_access,service,policy,direct):
    hops=[frame['edges'][(a,b)] for a,b in zip(path,path[1:])]
    s,t=source_access[path[0]],target_access[path[-1]]
    current=s['delay']+t['delay']+sum(h['current_ms'] for h in hops)
    planned=s['delay']+t['delay']+sum(h[field(policy)] for h in hops)
    length=s['distance']+t['distance']+sum(h['features']['distance_km'] for h in hops)
    bottleneck=min([s['capacity'],t['capacity']]+[h['bandwidth_mbps'] for h in hops])
    budget=APPLICATION_PROFILES[service]['latency_budget_ms']
    profile=SERVICES[service]
    score=profile['latency_weight']*planned+profile['distance_weight']*length/100+profile['capacity_weight']*100*(1/s['capacity']+1/t['capacity']+sum(1/h['bandwidth_mbps'] for h in hops))
    return dict(path=path,hops=hops,sourceId=path[0],targetId=path[-1],sourceCapacityMbps=s['capacity'],receiver_capacity_mbps=t['capacity'],
        hop_count=len(hops),distance_km=length,path_stretch=length/max(1,direct),bottleneck=bottleneck,
        score=score,cost=score,routing_policy=policy,model=frame['model'] if policy=='predictive' else None,motion_clock_s=frame['now'],
        positions=[dict(id=key,type=frame['nodes'][key].type,lat=frame['nodes'][key].lat,lng=frame['nodes'][key].lng,alt=frame['nodes'][key].alt) for key in path],
        application=dict(estimated_one_way_ms=current,planning_one_way_ms=planned,latency_budget_ms=budget,latency_budget_met=current<=budget,
            payload_bytes=APPLICATION_PROFILES[service]['payload_bytes'],required_bandwidth_mbps=profile['min_bandwidth']))


def endpoints(frame,source,target,service,server_id=None):
    starts=access(frame,source,service)
    if target:
        ends=access(frame,target,service)
        direct=surface_distance(source,target)
    else:
        ends={n.id:dict(distance=0,capacity=n.bandwidth,delay=2) for n in frame['nodes'].values() if n.type=='GROUND' and (not server_id or n.id==server_id)}
        direct=min((surface_distance(source,frame['nodes'][key]) for key in ends),default=0)
    return starts,ends,direct


def route(frame,source,target,service,policy,server_id=None,max_stretch=2):
    if policy=='predictive' and not frame['model']:return None,'Chưa có checkpoint FL phù hợp.'
    starts,ends,direct=endpoints(frame,source,target,service,server_id)
    if not starts or not ends:return None,'Một đầu không có node truy cập trong tầm và tầm nhìn.'
    max_distance=max(1500,direct*max_stretch+2*max((n.alt for n in frame['nodes'].values()),default=0)+100)
    demand=SERVICES[service]['min_bandwidth'];profile=SERVICES[service]
    adjacency={key:[] for key in frame['nodes']}
    for hop in frame['edges'].values():
        if hop['bandwidth_mbps']>=demand:adjacency[hop['source']].append(hop)
    # Bounded Pareto labels prevent an inexpensive but over-budget path from
    # masking a feasible alternative. A second pass reports degraded service.
    for budget in (APPLICATION_PROFILES[service]['latency_budget_ms'],math.inf):
        queue=[];labels={};serial=0;best=None
        for key,a in starts.items():
            score=profile['latency_weight']*a['delay']+profile['distance_weight']*a['distance']/100+profile['capacity_weight']*100/a['capacity']
            heapq.heappush(queue,(score,serial,a['delay'],a['distance'],[key]));serial+=1
        while queue:
            score,_,delay,length,path=heapq.heappop(queue);key=path[-1]
            if best is not None and score>=best['score']:break
            if key in ends:
                e=ends[key]
                if delay+e['delay']<=budget and length+e['distance']<=max_distance:
                    candidate=make_route(frame,path,starts,ends,service,policy,direct)
                    if best is None or candidate['score']<best['score']:best=candidate
            if len(path)>32:continue
            for hop in adjacency[key]:
                neighbor=hop['target']
                if neighbor in path:continue
                qos_delay=max(hop['current_ms'],hop['predicted_ms']) if policy=='predictive' else hop['current_ms']
                next_delay=delay+qos_delay;next_length=length+hop['features']['distance_km']
                if next_delay>budget or next_length>max_distance:continue
                next_score=score+profile['latency_weight']*hop[field(policy)]+profile['distance_weight']*hop['features']['distance_km']/100+profile['capacity_weight']*100/hop['bandwidth_mbps']
                known=labels.setdefault(neighbor,[])
                if any(c<=next_score and d<=next_delay and length0<=next_length for c,d,length0 in known):continue
                known[:]=[(c,d,l) for c,d,l in known if not (next_score<=c and next_delay<=d and next_length<=l)]
                known.append((next_score,next_delay,next_length));known.sort();del known[8:]
                heapq.heappush(queue,(next_score,serial,next_delay,next_length,path+[neighbor]));serial+=1
        if best:return best,'Đã xét vùng phủ hai đầu, ngân sách độ trễ và giới hạn độ vòng.'
    return None,'Không có tuyến đủ băng thông trong giới hạn khoảng cách hiện tại.'


def refresh_route(frame,old,source,target,service,policy,server_id=None,max_stretch=2):
    starts,ends,direct=endpoints(frame,source,target,service,server_id)
    path=old['path']
    if not path or path[0] not in starts or path[-1] not in ends:return None
    if any((a,b) not in frame['edges'] for a,b in zip(path,path[1:])):return None
    if any(frame['edges'][(a,b)]['bandwidth_mbps']<SERVICES[service]['min_bandwidth'] for a,b in zip(path,path[1:])):return None
    if policy=='predictive' and not frame['model']:return None
    result=make_route(frame,path,starts,ends,service,policy,direct)
    limit=max(1500,direct*max_stretch+2*max((n.alt for n in frame['nodes'].values()),default=0)+100)
    return result if result['distance_km']<=limit else None


def accept_change(old,new,now,last_switch,minimum_hold=10,improvement=.15):
    if not old:return True,'initial_or_broken'
    if [r['path'] for r in old]==[r['path'] for r in new]:return False,'same_path'
    old_ok=all(r['application']['latency_budget_met'] for r in old)
    new_ok=all(r['application']['latency_budget_met'] for r in new)
    if old_ok and not new_ok:return False,'protect_qos'
    if now-last_switch<minimum_hold:return False,'minimum_hold'
    if new_ok and not old_ok:return True,'qos_recovery'
    a=sum(r['score'] for r in old);b=sum(r['score'] for r in new)
    return (True,'improved') if b<a*(1-improvement) else (False,'below_improvement_threshold')
