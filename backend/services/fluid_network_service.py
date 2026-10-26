"""Shared-link allocation from B, applied to A's persisted global event routes."""
from copy import deepcopy
from sqlalchemy.orm import Session
from backend.models.network_learning import NetworkClock, NetworkAllocationSettings
from backend.models.network import Node,NetworkLink
from backend.models.routing_event import RoutingEvent
from backend.models.scenario import Scenario
from backend.schemas.routing import EventRouteRequest
from sagsin.allocation import allocate, assert_capacity


def clock_for(db,scenario_id):
    clock=db.get(NetworkClock,scenario_id)
    if clock is None:
        clock=NetworkClock(scenario_id=scenario_id,sim_time_s=0)
        db.add(clock);db.flush()
    return clock


def bind(db,result,request,previous=None):
    if result.get("runtime")!="federated-http-v3":return result
    now=clock_for(db,request.scenario_id).sim_time_s
    settings=db.get(NetworkAllocationSettings,request.scenario_id)
    policy=result.get("allocation_policy",request.allocation_policy)
    if settings:settings.policy=policy
    else:db.add(NetworkAllocationSettings(scenario_id=request.scenario_id,policy=policy))
    flow=deepcopy(previous) if previous and previous.get("engine")=="shared-fluid-v3" else dict(
        engine="shared-fluid-v3",created_s=now,remaining_mbit=result["profile"]["min_bandwidth"]*request.duration_s,
        total_mbit=result["profile"]["min_bandwidth"]*request.duration_s,deadline_s=now+request.duration_s+request.wait_timeout_s,
        allocated_mbps=result["profile"]["min_bandwidth"],delivered_mbit=0,reroutes=0,history=[])
    if flow.get("state") in {"completed","expired"}:return {**result,"flow":flow}
    flow["state"]="transmitting" if result.get("code")=="ok" else "waiting"
    return {**result,"flow":flow}


def advance(db,clock,seconds):
    from backend.services.routing_service import route_event
    clock.sim_time_s+=seconds
    now=clock.sim_time_s
    events=db.query(RoutingEvent).filter_by(scenario_id=clock.scenario_id).order_by(RoutingEvent.id).all()
    nodes={n.id:n for n in db.query(Node).filter_by(scenario_id=clock.scenario_id)}
    legacy_nodes={};legacy_links={}
    for event in events:
        result=event.result_json or {}
        if (result.get("flow") or {}).get("engine")=="shared-fluid-v3":continue
        if result.get("flow") and result["flow"]["state"]!="transmitting":continue
        route=result.get("route") or {}
        for key in set(route.get("path",[])):legacy_nodes[key]=legacy_nodes.get(key,0)+result["profile"]["min_bandwidth"]
        for hop in route.get("hops",[]):
            key=str(hop["link_id"]);legacy_links[key]=legacy_links.get(key,0)+result["profile"]["min_bandwidth"]
    settings=db.get(NetworkAllocationSettings,clock.scenario_id)
    policy=settings.policy if settings else next((e.result_json.get("allocation_policy","deadline") for e in events if (e.result_json.get("flow") or {}).get("engine")=="shared-fluid-v3"),"deadline")
    active=[];caps={};by_id={}
    for event in events:
        result=deepcopy(event.result_json or {})
        flow=result.get("flow") or {}
        if flow.get("engine")!="shared-fluid-v3" or flow.get("state") in {"completed","expired"}:continue
        if now-seconds>=flow["deadline_s"]:
            flow.update(state="expired",allocated_mbps=0,bandwidth_reserved=False)
            result["flow"]=flow;event.result_json=result;continue
        route=result.get("route") or {}
        broken=not route or any(k not in nodes or nodes[k].status!="ACTIVE" for k in route.get("path",[]))
        if broken or now-flow.get("last_route_s",-3)>=3:
            request=EventRouteRequest(**{**event.config_json,"lat":event.lat,"lng":event.lng,"service":event.service})
            updated=route_event(db,request,reservations={})
            new_route=updated.get("route") or {}
            if new_route:
                old_cost=route.get("total_predicted_transfer_ms",float("inf"))
                new_cost=new_route.get("total_predicted_transfer_ms",float("inf"))
                changed=route.get("path")!=new_route.get("path")
                if broken or not changed or new_cost<old_cost*.85:
                    if changed and route:flow["reroutes"]+=1;flow["pause_s"]=.05
                    result=updated;route=new_route
            else:
                result=updated;route={}
            flow["last_route_s"]=now
        path=[]
        for key in (route.get("path") or []):
            resource="node:"+key
            caps[resource]=max(0,nodes[key].bandwidth-legacy_nodes.get(key,0))
            path.append(resource)
        for hop in route.get("hops",[]):
            resource="link:"+str(hop["link_id"])
            available=max(0,hop["bandwidth_mbps"]-legacy_links.get(str(hop["link_id"]),0))
            stored=db.get(NetworkLink,hop["link_id"]) if hop.get("link_id") else None
            if stored is not None and stored.status!="ACTIVE":available=0
            caps[resource]=min(caps.get(resource,available),available)
            path.append(resource)
        resource=f"access:{event.id}"
        caps[resource]=route.get("sourceCapacityMbps",route.get("bottleneck",0))
        if path:path.append(resource)
        flow.update(state="transmitting" if path else "waiting",allocated_mbps=0,bandwidth_reserved=bool(path))
        result["flow"]=flow;event.result_json=result
        if path and flow["deadline_s"]>now-seconds:
            active.append(dict(id=event.id,path=path,remaining_mbit=flow["remaining_mbit"],time_left_s=flow["deadline_s"]-(now-seconds)))
            by_id[event.id]=(event,result)
    rates=allocate(active,caps,policy)
    assert_capacity(active,rates,caps)
    for item in active:
        event,result=by_id[item["id"]];flow=result["flow"]
        rate=rates[event.id]
        served=min(flow["remaining_mbit"],rate*max(0,min(seconds,flow["deadline_s"]-(now-seconds))-flow.pop("pause_s",0)))
        flow["remaining_mbit"]-=served;flow["delivered_mbit"]+=served
        flow["allocated_mbps"]=rate;flow["bandwidth_reserved"]=rate>0
        if flow["remaining_mbit"]<=1e-8:flow.update(state="completed",allocated_mbps=0,bandwidth_reserved=False,completed_s=now)
        elif now>=flow["deadline_s"]:flow.update(state="expired",allocated_mbps=0,bandwidth_reserved=False)
        flow["history"]=(flow["history"]+[dict(at_s=now,rate_mbps=rate,served_mbit=served,state=flow["state"])])[-60:]
        result["allocation"]={**result.get("allocation",{}),"engine":"shared-fluid-v3","policy":policy,
            "allocated_mbps":rate,"capacity_violations":0,"clock_s":now}
        event.result_json=result
    db.flush()


def tick(bind,seconds):
    with Session(bind) as db:
        for identifier, in db.query(NetworkClock.scenario_id).all():
            db.query(Scenario).filter_by(id=identifier).with_for_update().first()
            advance(db,db.get(NetworkClock,identifier),seconds)
        db.commit()
