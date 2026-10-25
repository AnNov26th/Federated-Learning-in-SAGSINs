"""Reservations are derived from saved routes, never supplied by the browser.

One flow reserves its requested Mbps once per visited node and once per
undirected link. Reservations include planned routes awaiting deployment and
last until deletion or an explicit recalculation of that event.
"""
from collections import defaultdict

from backend.models.routing_event import RoutingEvent
from backend.models.network import Node


def reservations_for(db, scenario_id, exclude_id=None):
    # Writers lock the scenario first. Locking reads also avoid stale snapshots
    # under MySQL's default REPEATABLE READ isolation.
    events = db.query(RoutingEvent).filter(RoutingEvent.scenario_id == scenario_id)
    if exclude_id is not None:
        events = events.filter(RoutingEvent.id != exclude_id)
    nodes, links, positions = defaultdict(float), defaultdict(float), {}
    count, deploying, locked = 0, set(), set()
    original_positions = {node.id: (node.lat, node.lng) for node in
                          db.query(Node).filter(Node.scenario_id == scenario_id)}
    for event in events.order_by(RoutingEvent.id).with_for_update():
        result = event.result_json or {}
        if result.get("flow") and result["flow"]["state"] != "transmitting":
            continue
        route = result.get("route")
        if not route:
            continue
        demand = result["profile"]["min_bandwidth"]
        count += 1
        for node_id in set(route["path"]):
            nodes[node_id] += demand
        # A later flow can keep using a deployed position after the event that
        # originally moved the node is deleted. Its own snapshot holds that pose.
        for node in route["positions"]:
            original = original_positions.get(node["id"])
            if original and (abs(original[0] - node["lat"]) > 1e-9 or abs(original[1] - node["lng"]) > 1e-9):
                positions[node["id"]] = node
        for hop in route["hops"]:
            links[tuple(sorted((hop["source"], hop["target"])))] += demand
        for move in (result.get("mobility") or {}).get("moves", []):
            positions[move["node_id"]] = move["to"]
            locked.add(move["node_id"])
            if (event.playback_json or {}).get("elapsed_s", 0) < result["mobility"]["eta_s"]:
                deploying.add(move["node_id"])
    return {"nodes": dict(nodes), "links": dict(links), "positions": positions,
            "deploying_nodes": deploying, "locked_nodes": locked, "event_count": count}


def serialize_event(event):
    return {"id": event.id, "display_number": event.display_number, "name": f"Điểm {event.display_number}",
            "scenario_id": event.scenario_id, "service": event.service,
            "lat": event.lat, "lng": event.lng, "config": event.config_json,
            "result": event.result_json, "playback": event.playback_json,
            "created_at": event.created_at.isoformat()}
