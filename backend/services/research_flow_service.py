"""Persistent finite flows on a shared simulation clock, with bounded retries."""

from copy import deepcopy
from backend.models.routing_event import RoutingEvent
from backend.models.scenario import Scenario
from backend.models.research_region import ResearchRegion
from backend.schemas.routing import EventRouteRequest
import asyncio
import logging
from starlette.concurrency import run_in_threadpool


def bind_flow(result, request, clock, previous=None):
    flow = (
        deepcopy(previous)
        if previous
        else {
            "created_s": clock,
            "remaining_s": request.duration_s,
            "deadline_s": clock + request.wait_timeout_s,
            "elapsed_transmitting_s": 0.0,
            "history": [],
            "handover_count": 0,
        }
    )
    old_state = flow.get("state")
    if old_state in {"completed", "expired"}:
        return {**result, "flow": flow}
    routed = result.get("code") == "ok"
    if not routed and clock >= flow["deadline_s"]:
        state = "expired"
    else:
        state = "transmitting" if routed else "waiting"
    if state != old_state:
        flow["history"] = (
            flow["history"]
            + [{"at_s": clock, "state": state, "reason": result.get("code")}]
        )[-20:]
    if routed and old_state == "waiting":
        flow["deadline_s"] = clock + request.wait_timeout_s
    flow.update(state=state, last_update_s=clock, bandwidth_reserved=routed)
    return {**result, "flow": flow}


def advance_region(db, region, seconds):
    region.sim_time_s += seconds
    clock = region.sim_time_s
    from backend.services.routing_service import route_event
    from backend.services.routing_event_service import reservations_for

    config = region.config_json
    events = (
        db.query(RoutingEvent)
        .filter_by(scenario_id=region.scenario_id)
        .order_by(RoutingEvent.id)
        .all()
    )
    for event in events:
        result = deepcopy(event.result_json or {})
        flow = result.get("flow")
        if not flow or flow["state"] in {"completed", "expired"}:
            continue
        route = result.get("route") or {}
        affected = bool(
            set(route.get("path", [])) & set(config["disabled_nodes"])
        ) or any(
            hop.get("link_id") in config.get("disabled_links", [])
            for hop in route.get("hops", [])
        )
        if flow["state"] == "transmitting" and not affected:
            from backend.models.network import NetworkLink, Node
            from backend.services.link_telemetry_service import telemetry
            from backend.services.research_region_service import link_load

            others = reservations_for(db, region.scenario_id, event.id)
            demand = result["profile"]["min_bandwidth"]
            load = event.config_json.get("load_ratio", 0.35)
            for identifier in route.get("path", []):
                node = db.get(Node, identifier)
                if (
                    not node
                    or node.bandwidth * (1 - 0.65 * load)
                    - others["nodes"].get(identifier, 0)
                    < demand
                ):
                    affected = True
                    break
            for hop in route.get("hops", []):
                stored = db.get(NetworkLink, hop["link_id"])
                if not stored or stored.status != "ACTIVE":
                    affected = True
                    break
                channel = {
                    key: getattr(stored, key)
                    for key in (
                        "id",
                        "source",
                        "target",
                        "bandwidth",
                        "latency",
                        "distance",
                    )
                }
                reserved = others["links"].get(
                    tuple(sorted((stored.source, stored.target))), 0.0
                )
                features = telemetry(
                    channel,
                    "GROUND",
                    clock,
                    result["payload_bytes"],
                    min(0.98, link_load(region, channel) + load * 0.3),
                    reserved,
                )
                if features["available_mbps"] < demand:
                    affected = True
                    break
        if flow["state"] == "transmitting":
            # Faults apply at this step boundary, before any new transmission.
            delta = 0 if affected else max(0.0, clock - flow["last_update_s"])
            sent = min(delta, flow["remaining_s"])
            flow["remaining_s"] -= sent
            flow["elapsed_transmitting_s"] += sent
            flow["last_update_s"] = clock
            if flow["remaining_s"] <= 1e-9:
                flow.update(
                    state="completed", bandwidth_reserved=False, completed_s=clock
                )
                flow["history"].append({"at_s": clock, "state": "completed"})
            elif affected:
                flow.update(
                    state="waiting",
                    bandwidth_reserved=False,
                    deadline_s=clock + event.config_json.get("wait_timeout_s", 30),
                )
                flow["handover_count"] += 1
                flow["history"].append(
                    {
                        "at_s": clock,
                        "state": "waiting",
                        "reason": "link_or_node_failure",
                    }
                )
            result["flow"] = flow
            event.result_json = result
            db.flush()
        if flow["state"] == "waiting":
            request = EventRouteRequest(
                **{
                    **event.config_json,
                    "lat": event.lat,
                    "lng": event.lng,
                    "service": event.service,
                }
            )
            if clock >= flow["deadline_s"]:
                flow.update(state="expired", bandwidth_reserved=False)
                flow["history"].append({"at_s": clock, "state": "expired"})
                event.result_json = {**result, "flow": flow}
                continue
            next_result = route_event(
                db, request, reservations_for(db, region.scenario_id, event.id)
            )
            next_result = bind_flow(next_result, request, clock, flow)
            event.result_json = next_result
            db.flush()
    db.flush()


def tick_running_regions(bind, seconds):
    from sqlalchemy.orm import Session

    with Session(bind) as db:
        ids = [
            identifier
            for identifier, in db.query(ResearchRegion.scenario_id).filter_by(
                running=True
            )
        ]
        for identifier in ids:
            db.query(Scenario).filter_by(id=identifier).with_for_update().first()
            region = (
                db.query(ResearchRegion)
                .filter_by(scenario_id=identifier)
                .with_for_update()
                .first()
            )
            if region.running:
                advance_region(db, region, seconds)
            db.commit()


async def run_clock(bind):
    """One shared clock per single-worker application, never per browser tab."""
    loop = asyncio.get_running_loop()
    previous = loop.time()
    while True:
        await asyncio.sleep(1)
        now = loop.time()
        seconds = min(5.0, now - previous)
        previous = now
        try:
            await run_in_threadpool(tick_running_regions, bind, seconds)
        except Exception:
            logging.getLogger(__name__).exception("Research simulation clock failed")
