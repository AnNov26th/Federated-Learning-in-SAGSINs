"""Auditable FL-assisted routing on a database topology snapshot.

The saved regressor predicts next-tick FL-payload round trips. Applying that
regressor to individual hops is an experimental routing surrogate, NOT a
prediction of application latency. No held-out labels enter routing decisions.
"""
import heapq
import math
from types import SimpleNamespace
from datetime import datetime, timezone

from backend.algorithms.network_delay_model import FEATURE_VERSION, load_checkpoint, payload_bytes, predict
from backend.models.network import NetworkLink, Node
from backend.models.network_learning import NetworkDataset, NetworkRoundEvaluation
from backend.models.simulation import Experiment, FLRound
from backend.services.delay_service import NETWORK_PROFILES, estimate_communication_ms
from backend.services.event_device_service import resolve_event, device_access_limit, elevation_deg
from backend.services.link_telemetry_service import LINK_TARGET, telemetry
from backend.services.research_region_service import region_for, link_load


SERVICES = {
    "Message": {"latency_weight": .55, "capacity_weight": .1, "distance_weight": .1, "min_bandwidth": .05},
    "Video Call": {"latency_weight": .45, "capacity_weight": .4, "distance_weight": .2, "min_bandwidth": 2},
    "Watch Video": {"latency_weight": .2, "capacity_weight": .75, "distance_weight": .15, "min_bandwidth": 5},
    "Gaming": {"latency_weight": .8, "capacity_weight": .08, "distance_weight": .3, "min_bandwidth": 1},
    "Emergency": {"latency_weight": 1, "capacity_weight": .15, "distance_weight": .1, "min_bandwidth": .1},
}
REMOTE_GROUND_THRESHOLD_KM = 500
REMOTE_INGRESS_PENALTY = {
    "Emergency": {"SPACE": 0, "AIR": 1, "SEA": 2, "GROUND": 3},
    "Message": {"SPACE": 0, "SEA": 1, "AIR": 2, "GROUND": 3},
    "Video Call": {"SPACE": 0, "AIR": 1, "SEA": 2, "GROUND": 3},
    "Watch Video": {"SPACE": 0, "AIR": 1, "SEA": 2, "GROUND": 3},
    "Gaming": {"AIR": 0, "SPACE": 1, "SEA": 2, "GROUND": 3},
}
LOCAL_INGRESS_PENALTY = {"GROUND": 0, "AIR": 1, "SEA": 2, "SPACE": 3}
ACCESS_LIMITS_KM = {"GROUND": 50, "SEA": 200, "AIR": 1500, "SPACE": 5000}
# Explicit demo assumptions, not guarantees or standardized service limits.
APPLICATION_PROFILES = {
    "Message": {"payload_bytes": 4096, "latency_budget_ms": 1000},
    "Video Call": {"payload_bytes": 1200, "latency_budget_ms": 150},
    "Watch Video": {"payload_bytes": 65536, "latency_budget_ms": 2000},
    "Gaming": {"payload_bytes": 256, "latency_budget_ms": 50},
    "Emergency": {"payload_bytes": 1024, "latency_budget_ms": 100},
}


def application_metrics(route, ingress, service, profile, event=None):
    """One-way store-and-forward estimate in bytes/Mbps, independent of FL RTT."""
    assumptions = APPLICATION_PROFILES[service]
    channels = [(ingress["access_latency_ms"], ingress["bandwidth_mbps"])] + [
        (hop["features"]["latency_ms"], hop["bandwidth_mbps"]) for hop in route["hops"]
    ]
    propagation = sum(latency for latency, _ in channels)
    serialization = sum(assumptions["payload_bytes"] * 8 / (bandwidth * 1000) for _, bandwidth in channels)
    processing = (event["device"]["processing_ms"] + event["traffic"]["processing_ms"]) if event and event["device"] else 0.
    delay = propagation + serialization + processing
    return {**assumptions, "estimated_one_way_ms": delay,
            "channel_latency_ms": propagation, "serialization_ms": serialization,
            "endpoint_processing_ms": processing,
            "latency_budget_met": delay <= assumptions["latency_budget_ms"],
            "required_bandwidth_mbps": profile["min_bandwidth"],
            "bandwidth_headroom_mbps": route["bottleneck"] - profile["min_bandwidth"],
            "source": "simulated_store_and_forward_no_contention_reservation",
            "note": "Ước tính một chiều gồm tiếp cận, các hop và xử lý đầu cuối khi có profile thiết bị. Ngưỡng/payload là giả định demo. Liên kết được giả định đối xứng; chưa mô phỏng tranh chấp vô tuyến hay hàng đợi gói."}
MODEL_NOTE = (
    "Model FL dự đoán RTT của payload huấn luyện ở tick tiếp theo. Tổng dự đoán "
    "của tiếp cận và từng hop là chỉ số thay thế để xếp hạng tuyến, chưa được kiểm chứng cho "
    "độ trễ đầu-cuối của ứng dụng. Tải, loss, jitter và RTT đầu vào là mô phỏng."
)


def finite(value, positive=False):
    try:
        number = float(value)
        return math.isfinite(number) and (number > 0 if positive else number >= 0)
    except (ValueError, TypeError):
        return False


def surface_distance(a, b):
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b.lng - a.lng) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def channel_distance(a, b):
    angle = surface_distance(a, b) / 6371
    r1, r2 = 6371 + max(0, a.alt), 6371 + max(0, b.alt)
    return math.sqrt(max(0, r1*r1 + r2*r2 - 2*r1*r2*math.cos(angle)))


def visible(a, b):
    # Surface access can be a global virtual channel; elevated radio channels
    # additionally require a geometric horizon (no links through the Earth).
    if max(a.alt, b.alt) <= 0:
        return True
    horizon = sum(math.acos(6371 / (6371 + max(0, n.alt))) for n in (a, b))
    return surface_distance(a, b) / 6371 <= horizon + 1e-9


def model_candidates(db, scenario_id=None):
    query = db.query(Experiment, FLRound, NetworkRoundEvaluation).join(
        FLRound, FLRound.experiment_id == Experiment.id,
    ).join(NetworkRoundEvaluation, NetworkRoundEvaluation.round_id == FLRound.id).filter(
        Experiment.status == "COMPLETED", FLRound.participants_count > 0,
        Experiment.algorithm.in_(["Predictive", "FedAvg", "DelayAware"]),
    )
    if scenario_id is not None:
        query = query.filter(Experiment.scenario_id == scenario_id)
    result, seen = [], set()
    for experiment, round_row, evaluation in query.order_by(Experiment.id.desc(), FLRound.round.desc()):
        config = experiment.config_json or {}
        if experiment.id in seen or config.get("task") != "network_delay":
            continue
        dataset = db.get(NetworkDataset, config.get("dataset_id"))
        if not dataset or dataset.scenario_id != experiment.scenario_id:
            continue
        if dataset.config_json.get("runtime")!="federated-http-v3" and (dataset.config_json.get("feature_version") != FEATURE_VERSION or dataset.config_json.get("target") not in {"next_tick_model_round_trip_ms", LINK_TARGET}):
            continue
        seen.add(experiment.id)
        result.append((experiment, round_row, evaluation, dataset))
    return result


def model_summary(candidate):
    experiment, round_row, evaluation, dataset = candidate
    return {"experiment_id": experiment.id, "scenario_id": experiment.scenario_id,
            "algorithm": experiment.algorithm, "round": round_row.round,
            "mae_ms": evaluation.mae_ms, "validation_mae_ms": evaluation.validation_mae_ms,
            "persistence_mae_ms": evaluation.persistence_mae_ms,
            "payload_bytes": dataset.config_json["payload_bytes"],
            "dataset_id": dataset.id, "target": dataset.config_json["target"],
            "candidate_pool": (experiment.config_json or {}).get("candidate_pool", []),
            "beats_persistence": evaluation.mae_ms < evaluation.persistence_mae_ms}


def estimated_links(nodes):
    # Bounded two-neighbor graph. Deliberately leave disconnected components
    # disconnected instead of inserting arbitrary global bridging links.
    pairs = {}
    for source in nodes:
        candidates = []
        for target in nodes:
            if source.id == target.id or not visible(source, target):
                continue
            distance = channel_distance(source, target)
            limit = 5000 if "SPACE" in (source.type, target.type) else 1500 if "AIR" in (source.type, target.type) else 500
            if distance <= limit:
                candidates.append((distance, target.id, target))
        for distance, _, target in sorted(candidates)[:2]:
            key = tuple(sorted((source.id, target.id)))
            pairs[key] = {"id": None, "source": source.id, "target": target.id,
                          "distance": distance, "latency": max(1, distance / 299.792458),
                          "bandwidth": min(source.bandwidth, target.bandwidth)}
    return list(pairs.values())


def adaptive_links(nodes, configured_links):
    """Add one-request virtual relays when the saved/nearby graph is sparse."""
    pairs = {}
    for link in configured_links:
        pairs[frozenset((link["source"], link["target"]))] = {**link, "estimated": False}
    ordered = list(nodes.values())
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if not visible(first, second):
                continue
            distance = channel_distance(first, second)
            if "SPACE" in (first.type, second.type):
                limit = 5000
            elif "AIR" in (first.type, second.type):
                limit = 1500
            elif first.type == second.type == "GROUND":
                # A terrestrial/backbone link is an explicit simulation assumption.
                limit = 20000
            else:
                limit = 500
            if distance > limit:
                continue
            key = frozenset((first.id, second.id))
            pairs.setdefault(key, {"id": None, "source": first.id, "target": second.id,
                                   "distance": distance,
                                   "latency": max(float(first.latency), float(second.latency), distance / 299.792458),
                                   "bandwidth": min(first.bandwidth, second.bandwidth), "estimated": True})
    return list(pairs.values())


def shortest_route(source, targets, nodes, edges, profile, field, source_capacity):
    adjacency = {node: [] for node in nodes}
    for edge in edges:
        adjacency[edge["source"]].append(edge)
    distances, previous, queue = {source: 0.}, {}, [(0., source)]
    while queue:
        cost, current = heapq.heappop(queue)
        if cost != distances[current]:
            continue
        if current in targets:
            hops, cursor = [], current
            while cursor != source:
                edge = previous[cursor]
                hops.append(edge)
                cursor = edge["source"]
            hops.reverse()
            return {"path": [source] + [hop["target"] for hop in hops], "hops": hops,
                    "cost": cost, "predicted_transfer_ms": sum(h["predicted_ms"] for h in hops) if all(h["predicted_ms"] is not None for h in hops) else None,
                    "static_transfer_ms": sum(h["static_ms"] for h in hops),
                    "bottleneck": min([source_capacity] + [h["bandwidth_mbps"] for h in hops])}
        for edge in adjacency[current]:
            value = edge[field]
            weight = profile["latency_weight"] * value + profile["capacity_weight"] * 100 / edge["bandwidth_mbps"]
            new_cost = cost + weight
            neighbor = edge["target"]
            if new_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                previous[neighbor] = edge
                heapq.heappush(queue, (new_cost, neighbor))
    return None


def topology_links(db, nodes, topology, position_overrides=None):
    configured = [{key: getattr(link, key) for key in ("id", "source", "target", "distance", "latency", "bandwidth")}
        for link in db.query(NetworkLink).filter(NetworkLink.status.ilike("ACTIVE")).order_by(NetworkLink.id)
        if link.source in nodes and link.target in nodes
        and not (position_overrides and (link.source in position_overrides or link.target in position_overrides))]
    if topology == "estimated":
        return [{**link, "estimated": True} for link in estimated_links(list(nodes.values()))]
    if topology == "adaptive":
        return adaptive_links(nodes, configured)
    return configured


def topology_preview(nodes, links):
    """A bounded drawing subset; routing still uses the complete graph."""
    adjacent = {key: [] for key in nodes}
    for index, link in enumerate(links):
        if finite(link["distance"]):
            for key in (link["source"], link["target"]):
                adjacent[key].append((link["distance"], index))
    selected = {index for candidates in adjacent.values() for _, index in sorted(candidates)[:3]}
    return {"nodes": [{"id": n.id, "type": n.type, "lat": n.lat, "lng": n.lng, "alt": n.alt} for n in nodes.values()],
            "links": [{key: links[index].get(key, False) for key in ("source", "target", "distance", "estimated")} for index in sorted(selected)],
            "total_links": len(links), "neighbors_shown": 3}


def routing_topology(db, scenario_id, topology):
    research=region_for(db,scenario_id)
    nodes = {n.id: n for n in db.query(Node).filter(Node.scenario_id == scenario_id, Node.status.ilike("ACTIVE")).order_by(Node.id)
             if finite(n.bandwidth, True) and finite(n.latency) and n.type in ACCESS_LIMITS_KM}
    if research:nodes={key:node for key,node in nodes.items() if key not in research.config_json["disabled_nodes"]}
    links=topology_links(db,nodes,"configured" if research else topology)
    if research:links=[link for link in links if link["id"] not in research.config_json["disabled_links"]]
    return topology_preview(nodes, links)


def shortest_route_from_access(sources, targets, nodes, edges, profile, field):
    """Dijkstra with all eligible ingress nodes in one additive score space."""
    adjacency = {node: [] for node in nodes}
    for edge in edges:
        adjacency[edge["source"]].append(edge)
    roots = {item["source_id"]: item for item in sources}
    distances = {
        source_id: (profile["latency_weight"] * (item["predicted_access_rtt_ms"] if field == "predicted_ms" else item["access_rtt_ms"])
                    + profile["capacity_weight"] * 100 / item["bandwidth_mbps"]
                    + profile["distance_weight"] * item["distance_km"] / 100
                    + item.get("preference_penalty", 0))
        for source_id, item in roots.items()
    }
    previous, queue = {}, [(cost, source_id) for source_id, cost in distances.items()]
    heapq.heapify(queue)
    while queue:
        cost, current = heapq.heappop(queue)
        if cost != distances[current]:
            continue
        if current in targets:
            hops, cursor = [], current
            while cursor in previous:
                edge = previous[cursor]
                hops.append(edge)
                cursor = edge["source"]
            hops.reverse()
            ingress = roots[cursor]
            return {"path": [cursor] + [hop["target"] for hop in hops], "hops": hops,
                    "cost": cost, "predicted_transfer_ms": sum(h["predicted_ms"] for h in hops) if all(h["predicted_ms"] is not None for h in hops) else None,
                    "static_transfer_ms": sum(h["static_ms"] for h in hops),
                    "bottleneck": min([ingress["bandwidth_mbps"]] + [h["bandwidth_mbps"] for h in hops]),
                    "sourceId": cursor, "targetId": current, "accessDistanceKm": ingress["distance_km"],
                    "sourceCapacityMbps": ingress["bandwidth_mbps"],
                    "access_rtt_ms": ingress["access_rtt_ms"],
                    "predicted_access_rtt_ms": ingress.get("predicted_access_rtt_ms"),
                    "total_static_transfer_ms": ingress["access_rtt_ms"] + sum(h["static_ms"] for h in hops),
                    "total_predicted_transfer_ms": ingress["predicted_access_rtt_ms"] + sum(h["predicted_ms"] for h in hops) if ingress.get("predicted_access_rtt_ms") is not None and all(h["predicted_ms"] is not None for h in hops) else None,
                    "ingressPreferencePenalty": ingress.get("preference_penalty", 0)}
        for edge in adjacency[current]:
            value = edge[field]
            new_cost = (cost + profile["latency_weight"] * value
                        + profile["capacity_weight"] * 100 / edge["bandwidth_mbps"]
                        + profile["distance_weight"] * edge["features"]["distance_km"] / 100)
            neighbor = edge["target"]
            if new_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                previous[neighbor] = edge
                heapq.heappush(queue, (new_cost, neighbor))
    return None


def nearest_feasible_ingress(ingress, targets, edges):
    """Choose by physical distance only after checking residual connectivity."""
    incoming = {}
    for edge in edges:
        incoming.setdefault(edge["target"], []).append(edge["source"])
    reachable, pending = set(targets), list(targets)
    while pending:
        for source in incoming.get(pending.pop(), []):
            if source not in reachable:
                reachable.add(source)
                pending.append(source)
    candidates = sorted(ingress, key=lambda row: (row["distance_km"], row["source_id"]))
    return next(([row] for row in candidates if row["source_id"] in reachable), [])


def route_snapshot(db, request, position_overrides=None, ingress_ids=None, reservations=None):
    reservations = reservations or {}
    used_nodes, used_links = reservations.get("nodes", {}), reservations.get("links", {})
    research = region_for(db, request.scenario_id)
    profile = {**SERVICES[request.service]}
    if request.required_bandwidth_mbps is not None:
        profile["min_bandwidth"] = request.required_bandwidth_mbps
    event = resolve_event(request)
    nearest_access = request.source_device == "network_gateway"
    result = {"status": "unavailable", "reason": "", "route": None, "baseline": None,
              "policy": request.policy, "topology": request.topology, "model": None,
              "snapshot_at": datetime.now(timezone.utc).isoformat(), "note": MODEL_NOTE,
              "profile": profile, "scenario_id": request.scenario_id, "event_model": event}
    def fail(code, reason):
        return {**result, "code": code, "reason": reason}

    if event["device"] and event["device"]["effective_bandwidth_mbps"] < profile["min_bandwidth"]:
        return fail("device_capacity", "Thiết bị phát không đủ tốc độ cho dịch vụ này; chọn thiết bị hoặc giảm nhu cầu băng thông.")

    nodes = {n.id: n for n in db.query(Node).filter(Node.scenario_id == request.scenario_id, Node.status.ilike("ACTIVE")).order_by(Node.id)
             if finite(n.bandwidth, True) and finite(n.latency) and n.type in {"GROUND", "AIR", "SPACE", "SEA"}}
    if research:
        nodes={key:node for key,node in nodes.items() if key not in research.config_json.get("disabled_nodes", [])}
        result["research"]={"version":research.config_json["version"],"sim_time_s":research.sim_time_s,
            "conditions":research.config_json["conditions"],"access_nodes":research.config_json["access_nodes"],
            "service_nodes":research.config_json["service_nodes"]}
        result["topology"]="configured"
    if not nodes:
        return fail("no_nodes", "Scenario chưa có node ACTIVE hợp lệ.")
    for node_id, position in (position_overrides or {}).items():
        if node_id in nodes:
            node = nodes[node_id]
            nodes[node_id] = SimpleNamespace(**{key: getattr(node, key) for key in
                ("id", "type", "lat", "lng", "alt", "bandwidth", "latency", "status", "scenario_id")})
            nodes[node_id].lat, nodes[node_id].lng = position["lat"], position["lng"]
    origin = type("Origin", (), {"lat": request.lat, "lng": request.lng, "alt": 0.})()
    if event["device"]:
        compatible = []
        for node in nodes.values():
            reach = device_access_limit(event, node.type)
            if not reach:
                continue
            distance = channel_distance(origin, node)
            compatible.append({"node_id": node.id, "type": node.type, "lat": node.lat, "lng": node.lng,
                "distance_km": distance, "device_range_km": reach,
                "within_device_range": distance <= reach,
                "within_local_scope": request.routing_scope != "local" or distance <= request.local_radius_km})
        compatible.sort(key=lambda row: (row["distance_km"], row["node_id"]))
        result["coverage_diagnostics"] = {"nearest_compatible_nodes": compatible[:3],
            "note": "Khoảng cách tới node có lớp truy cập phù hợp; chưa khẳng định đủ tín hiệu, băng thông hoặc có backhaul."}
    local = request.routing_scope == "local"
    result["routing_scope"] = {"mode": request.routing_scope,
        "radius_km": request.local_radius_km if local else None,
        "distance_definition": "access_area_plus_layer_specific_backbone" if research else "3d_slant_from_event_and_per_hop" if local else "scenario",
        "expanded": False}
    if local:
        nodes = {key: node for key, node in nodes.items()
                 if (surface_distance(origin,node) if research else channel_distance(origin, node)) <= request.local_radius_km + 1e-9}
        if not nodes:
            return fail("no_local_nodes", f"Không có node ACTIVE trong vùng cục bộ {request.local_radius_km:g} km; không tự nối ra xa.")
    ground_distances = [surface_distance(origin, n) for n in nodes.values() if n.type == "GROUND"]
    if not ground_distances:
        return fail("no_local_target" if local else "no_target", "Không có GROUND ACTIVE trong vùng cục bộ; không tự chọn đích ngoài vùng." if local else "Scenario cần ít nhất một node GROUND ACTIVE làm đích.")
    nearest_ground_km = min(ground_distances)
    remote = nearest_ground_km > REMOTE_GROUND_THRESHOLD_KM
    # Global surface ingress is a virtual simulation channel, not radio coverage.
    # Elevated ingress still respects the horizon. Explicit radii remain strict.
    effective_access_radius = request.access_radius_km
    if local:
        effective_access_radius = min(effective_access_radius or request.local_radius_km, request.local_radius_km)
    result["access_search"] = {"requested_radius_km": request.access_radius_km,
                               "used_radius_km": effective_access_radius,
                               "mode": "global" if effective_access_radius is None else "bounded",
                               "expanded": False,
                               "nearest_ground_km": nearest_ground_km}
    if nearest_access:
        result["access_search"].update(mode="layer_bounded", limits_km=ACCESS_LIMITS_KM,
                                       selection="nearest_with_feasible_route")
    coverage = []
    for node in nodes.values():
        if research and node.id not in research.config_json["access_nodes"]:
            continue
        if ingress_ids is not None and node.id not in ingress_ids:
            continue
        distance = channel_distance(origin, node) if node.alt > 0 else surface_distance(origin, node)
        limit = effective_access_radius
        device_limit = device_access_limit(event, node.type)
        if device_limit == 0:
            continue
        if device_limit is not None:
            limit = min(limit, device_limit) if limit is not None else device_limit
            if node.type == "SPACE" and elevation_deg(origin, node) < event["device"].get("min_elevation_deg", 0):
                continue
        if request.allow_reposition or local or nearest_access:
            limit = min(limit, ACCESS_LIMITS_KM[node.type]) if limit is not None else ACCESS_LIMITS_KM[node.type]
        if visible(origin, node) and (limit is None or distance <= limit):
            coverage.append((distance, node.id, node))
    coverage.sort(key=lambda item: (item[0], item[1]))
    if not coverage:
        if nearest_access:
            return fail("no_coverage", "Không có node ACTIVE trong tầm tiếp cận theo lớp và tầm nhìn. Không tự nối tới node xa hoặc di chuyển node để tạo tuyến.")
        scope = "toàn scenario" if effective_access_radius is None else f"bán kính {effective_access_radius:.0f} km"
        if event["device"]:
            return fail("no_coverage", f"{event['device']['name']} không có node truy cập tương thích, đủ tầm và tầm nhìn trong {scope}. Không tự nâng cấp thiết bị hoặc mở rộng vùng.")
        return fail("no_coverage", f"Không có node ACTIVE trong tầm nhìn và {scope}. Không tự mở rộng vùng cục bộ." if local else f"Không có node ACTIVE trong tầm nhìn và {scope}. Hãy kiểm tra node hoặc bỏ giới hạn bán kính.")
    sources = [{"source_id": id, "distance_km": distance, "radius_km": effective_access_radius,
                "latency_ms": distance / 299.792458, "is_estimated": True}
               for distance, id, _ in coverage]
    result["access"] = sources[0]
    targets = {n.id for n in nodes.values() if n.type == "GROUND"}
    if research:targets &= set(research.config_json["service_nodes"])
    if request.target_id:
        if request.target_id not in targets:
            return fail("invalid_target", "Đích phải là node GROUND ACTIVE trong cùng scenario và phạm vi định tuyến đã chọn.")
        targets = {request.target_id}
    if not targets:
        return fail("no_target", "Scenario cần ít nhất một node GROUND ACTIVE làm đích.")

    if remote:
        preference_penalties = REMOTE_INGRESS_PENALTY[request.service]
        selection_reason = f"Xa GROUND gần nhất {nearest_ground_km:.0f} km. Tối ưu tổng điểm khoảng cách, băng thông và độ trễ; sở thích lớp theo sự kiện {request.service} chỉ là trọng số phụ."
    else:
        preference_penalties = LOCAL_INGRESS_PENALTY
        selection_reason = f"Cách GROUND gần nhất {nearest_ground_km:.0f} km. Tối ưu tổng điểm khoảng cách, băng thông và độ trễ; GROUND chỉ được ưu tiên nhẹ khi các chỉ số gần tương đương."

    chosen = None
    if request.policy == "predictive":
        candidates = model_candidates(db, request.scenario_id)
        if research:candidates=[candidate for candidate in candidates if candidate[3].config_json["target"] in {LINK_TARGET,"next_tick_reference_payload_delay_ms"}]
        chosen = next((c for c in candidates if c[0].id == request.experiment_id), None) if request.experiment_id else next(iter(candidates), None)
        if chosen is None:
            return fail("no_model", "Chưa có checkpoint FL hoàn tất phù hợp. Huấn luyện Network delay cho scenario này hoặc chọn công thức tĩnh.")
        result["model"] = model_summary(chosen)
    distributed_model=bool(chosen and chosen[3].config_json.get("runtime")=="federated-http-v3")
    model_links={e["id"]:e for e in chosen[0].config_json["distributed_config"]["topology"]["links"]} if distributed_model else {}
    link_task = bool(chosen and chosen[3].config_json["target"] in {LINK_TARGET,"next_tick_reference_payload_delay_ms"})
    if research and chosen and not link_task:
        return fail("incompatible_model", "Khu vực nghiên cứu cần checkpoint học độ trễ link ứng dụng.")

    links = topology_links(db, nodes, "configured" if research else request.topology, position_overrides)
    if nearest_access:
        from backend.services.topology_service import feasible_pair
        # Keep explicit terrestrial backhaul, but never invent long ground links
        # or trust stale stored distances to bypass snapshot geometry.
        links = [{**link, "distance": channel_distance(nodes[link["source"]], nodes[link["target"]])}
                 for link in links
                 if feasible_pair(nodes[link["source"]], nodes[link["target"]],
                                  allow_ground_backbone=not link.get("estimated", False))]
    if local:
        # Recompute geometry, including stored links: their saved distance must
        # not bypass a local bound or claim a link through the Earth.
        links = [{**link, "distance": channel_distance(nodes[link["source"]], nodes[link["target"]])}
                 for link in links
                 if visible(nodes[link["source"]], nodes[link["target"]])
                 and channel_distance(nodes[link["source"]], nodes[link["target"]]) <= (
                    5000 if research and "SPACE" in (nodes[link["source"]].type,nodes[link["target"]].type)
                    else 1500 if research and "AIR" in (nodes[link["source"]].type,nodes[link["target"]].type)
                    else request.local_radius_km) + 1e-9]
    if research:links=[link for link in links if link["id"] not in research.config_json.get("disabled_links",[])]
    size = chosen[3].config_json["payload_bytes"] if chosen else payload_bytes()
    if link_task or research:size=APPLICATION_PROFILES[request.service]["payload_bytes"]
    network_profile = NETWORK_PROFILES[chosen[3].config_json["network_profile"] if chosen else "normal"]
    def node_capacity(node, load):
        if node.id in reservations.get("deploying_nodes", set()):
            return 0.
        return max(0., node.bandwidth * network_profile["bandwidth_multiplier"] * (1 - .65 * load) - used_nodes.get(node.id, 0.))

    def link_capacity(link, load):
        reserved = used_links.get(tuple(sorted((link["source"], link["target"]))), 0.)
        return max(0., link["bandwidth"] * network_profile["bandwidth_multiplier"] * (1 - .65 * load) - reserved)

    def build_edges(load):
        edges, features, excluded = [], [], 0
        ingress = []
        for item in sources:
            node = nodes[item["source_id"]]
            capacity = node_capacity(node, load)
            if event["device"]:
                capacity = min(capacity, event["device"]["effective_bandwidth_mbps"])
            if capacity >= profile["min_bandwidth"]:
                access_latency = max(float(node.latency), item["distance_km"] / 299.792458) * network_profile["latency_multiplier"] * (1 + .8 * load) + 25 * load**2
                access_rtt = estimate_communication_ms(access_latency, capacity, size / (1024*1024)) / (1 - .04 * load**2)
                if distributed_model:access_rtt=access_latency+size*8/(capacity*1000)
                feature = {"layer": node.type, "observed_delay_ms": access_rtt,
                           "latency_ms": access_latency, "bandwidth_mbps": capacity,
                           "distance_km": item["distance_km"], "load_ratio": load,
                           "packet_loss_ratio": .04 * load**2, "jitter_ms": access_latency*.04,
                           "payload_bytes": size}
                if research:
                    access_link={"id":0,"distance":item["distance_km"],"bandwidth":capacity,"latency":max(1,item["distance_km"]/299.792458)}
                    feature=telemetry(access_link,node.type,research.sim_time_s,size,load)
                    access_latency=feature["latency_ms"];access_rtt=feature["observed_delay_ms"]
                    capacity=min(capacity,feature["available_mbps"])
                    if capacity < profile["min_bandwidth"]:continue
                ingress.append({**item, "bandwidth_mbps": capacity, "features": feature,
                                "predicted_access_rtt_ms": None,
                                "access_latency_ms": access_latency, "access_rtt_ms": access_rtt,
                                "preference_penalty": preference_penalties.get(node.type, 4)})
        for link in links:
            if not finite(link["bandwidth"], True) or not finite(link["latency"]) or not finite(link["distance"]):
                excluded += 1
                continue
            for first, second in ((link["source"], link["target"]), (link["target"], link["source"])):
                a, b = nodes[first], nodes[second]
                bandwidth = min(node_capacity(a, load), node_capacity(b, load), link_capacity(link, load))
                if bandwidth < profile["min_bandwidth"]:
                    excluded += 1
                    continue
                latency = max(a.latency, b.latency, link["latency"], link["distance"] / 299.792458) * network_profile["latency_multiplier"] * (1 + .8 * load) + 25 * load**2
                loss = .04 * load**2
                static = estimate_communication_ms(latency, bandwidth, size / (1024*1024)) / (1 - loss)
                feature = {"layer": b.type, "observed_delay_ms": static, "latency_ms": latency,
                           "bandwidth_mbps": bandwidth, "distance_km": link["distance"],
                           "load_ratio": load, "packet_loss_ratio": loss, "jitter_ms": latency*.04, "payload_bytes": size}
                if research:
                    reserved=used_links.get(tuple(sorted((first,second))),0.)
                    base_load=min(.98,link_load(research,link)+load*.3)
                    feature=telemetry(link,b.type,research.sim_time_s,size,base_load,reserved)
                    bandwidth=min(feature["available_mbps"],node_capacity(a,load),node_capacity(b,load))
                    if bandwidth < profile["min_bandwidth"]:excluded+=1;continue
                    static=feature["observed_delay_ms"]
                    future=telemetry(link,b.type,research.sim_time_s+1,size,base_load,reserved)["observed_delay_ms"]
                if distributed_model:
                    from backend.services.distributed_runtime_service import application_features
                    from backend.models.network_learning import NetworkClock
                    clock=db.get(NetworkClock,request.scenario_id)
                    tick=clock.sim_time_s if clock else 0
                    feature=application_features(link,b.type,tick,size,chosen[0].config_json["distributed_config"],load,
                        used_links.get(tuple(sorted((first,second))),0),model_links.get(f"A{link['id']}"))
                    bandwidth=min(bandwidth,feature["available_mbps"])
                    static=feature["observed_delay_ms"]
                    if bandwidth<profile["min_bandwidth"]:continue
                features.append(feature)
                edges.append({"link_id": link["id"], "source": first, "target": second,
                              "bandwidth_mbps": bandwidth, "static_ms": static, "predicted_ms": None,
                              "estimated": link.get("estimated", False), "features": feature})
                if research:edges[-1]["realized_next_tick_ms"]=future
        if nearest_access:
            ingress = nearest_feasible_ingress(ingress, targets, edges)
        return ingress, edges, features, excluded

    def static_route_at(load):
        ingress, candidate_edges, _, _ = build_edges(load)
        return shortest_route_from_access(ingress, targets, nodes, candidate_edges, profile, "static_ms")

    selected_load = request.load_ratio
    best_static = static_route_at(selected_load)
    if best_static is None and selected_load > 0 and request.allow_load_reduction:
        low, high = 0.0, selected_load
        if static_route_at(low) is None:
            return fail("no_path", f"Không tìm được tuyến tới GROUND ngay cả khi hạ tải mô phỏng về 0%. Thử topology thích ứng, tăng băng thông hoặc chọn điểm/node GROUND khác. Điều kiện dịch vụ: ≥ {profile['min_bandwidth']} Mbps.")
        for _ in range(10):
            middle = (low + high) / 2
            if static_route_at(middle) is None:
                high = middle
            else:
                low = middle
        selected_load = low
        best_static = static_route_at(selected_load)

    ingress, edges, features, excluded = build_edges(selected_load)
    result["diagnostics"] = {"active_nodes": len(nodes), "links": len(links), "eligible_directions": len(edges), "excluded": excluded}
    inference_features = features + ([] if distributed_model else [item["features"] for item in ingress])
    if distributed_model:
        for item in ingress:item["predicted_access_rtt_ms"]=item["access_rtt_ms"]
    if chosen and inference_features:
        if distributed_model:
            from backend.services.distributed_runtime_service import predict_features
            predictions=predict_features(chosen[2].checkpoint_json,inference_features)
        else:
            from backend.services.fl_service import _training_lock
            with _training_lock:
                predictions = predict(load_checkpoint(chosen[2].checkpoint_json), inference_features)
        if len(predictions) != len(inference_features) or any(not finite(value) for value in predictions):
            return fail("invalid_prediction", "Model trả về dự đoán không hợp lệ; hãy kiểm tra checkpoint.")
        for edge, prediction in zip(edges, predictions):
            edge["predicted_ms"] = prediction
        for item, prediction in zip(ingress, predictions[len(edges):]):
            item["predicted_access_rtt_ms"] = prediction
    # Score both policies against the same rebuilt edge objects so the static
    # baseline also carries model predictions for like-for-like comparison.
    baseline = shortest_route_from_access(ingress, targets, nodes, edges, profile, "static_ms")
    best = shortest_route_from_access(ingress, targets, nodes, edges, profile, "predicted_ms") if chosen else baseline
    if best is None:
        return fail("no_path", f"Không tìm thấy tuyến có băng thông còn lại ≥ {profile['min_bandwidth']} Mbps sau khi trừ phần đã cấp cho {reservations.get('event_count', 0)} điểm khác.")
    if nearest_access:
        selected_access = next(item for item in ingress if item["source_id"] == best["sourceId"])
        result["access"] = {key: value for key, value in selected_access.items() if key != "features"}
        selection_reason = "Chọn node gần nhất thỏa tầm tiếp cận, tầm nhìn, băng thông còn lại và có đường tới GROUND. FL chọn tuyến tiếp theo từ cùng node đầu vào với đối chứng."
    def decorate(route, predictive=False):
        access = next(item for item in ingress if item["source_id"] == route["sourceId"])
        delay = route["total_predicted_transfer_ms"] if predictive else route["total_static_transfer_ms"]
        distance = access["distance_km"] + sum(h["features"]["distance_km"] for h in route["hops"])
        capacity_cost = profile["capacity_weight"] * 100 * (1 / access["bandwidth_mbps"] + sum(1 / h["bandwidth_mbps"] for h in route["hops"]))
        return {**route, "hop_count": len(route["hops"]),
                "application": application_metrics(route, access, request.service, profile, event),
                "distance_km": distance,
                "score_breakdown": {"delay": profile["latency_weight"] * delay,
                                    "capacity": capacity_cost,
                                    "distance": profile["distance_weight"] * distance / 100,
                                    "preference": route["ingressPreferencePenalty"],
                                    "total": route["cost"]},
                "access": {**access, "mode": result["access_search"]["mode"],
                           "virtual": effective_access_radius is None and not request.allow_reposition and not nearest_access,
                           "note": "Tiếp cận thỏa vùng phủ và tầm nhìn của phương tiện trong mô phỏng." if request.allow_reposition or local else "Kênh tiếp cận ước tính toàn scenario; không khẳng định phủ sóng vô tuyến thực tế." if effective_access_radius is None else "Kênh tiếp cận ước tính trong bán kính đã chọn."},
                "estimated_hops": sum(hop["estimated"] for hop in route["hops"]),
                "positions": [{"id": id, "type": nodes[id].type, "lat": nodes[id].lat, "lng": nodes[id].lng, "alt": nodes[id].alt} for id in route["path"]]}
    result.update(status="routed", code="ok", reason="Đã chọn tuyến có tổng chi phí nhỏ nhất.",
                  route=decorate(best, predictive=chosen is not None), baseline=decorate(baseline), payload_bytes=size,
                  topology_preview=topology_preview(nodes, links),
                  requested_load_ratio=request.load_ratio, applied_load_ratio=selected_load,
                  load_reduced=selected_load < request.load_ratio,
                  ingress_selection={"remote": remote, "nearest_ground_km": nearest_ground_km,
                                     "preference_penalties": preference_penalties,
                                     "chosen_type": nodes[best["path"][0]].type,
                                     "chosen_node": best["path"][0],
                                     "access_distance_km": best["accessDistanceKm"],
                                     "access_rtt_ms": next(item["access_rtt_ms"] for item in ingress if item["source_id"] == best["path"][0]),
                                     "predicted_access_rtt_ms": best["predicted_access_rtt_ms"],
                                     "access_bandwidth_mbps": best["sourceCapacityMbps"],
                                     "total_cost": best["cost"], "preference_penalty": best["ingressPreferencePenalty"],
                                     "reason": selection_reason},
                  objective="Ingress + Σ hop: w_delay × RTT_proxy_ms + w_capacity × 100 / bandwidth_Mbps + w_distance × distance_km / 100 + soft_ingress_preference_penalty")
    result["destination"] = {"node_id": best["targetId"], "role": event["traffic"]["destination"],
        "placement": "assumed_service_at_ground_edge", "processing_ms": event["traffic"]["processing_ms"]}
    if nearest_access:
        result["ingress_selection"].update(method="nearest_feasible", access_limits_km=ACCESS_LIMITS_KM)
        result["route"]["access"]["note"] = "Kênh truy cập trừu tượng, có giới hạn khoảng cách theo lớp node và kiểm tra tầm nhìn; không mô phỏng radio thiết bị cá nhân."
    result["routing_decision"] = {"method": "fl_checkpoint" if chosen else "static_formula",
        "experiment_id": chosen[0].id if chosen else None, "round": chosen[1].round if chosen else None,
        "feasibility_first": True, "prediction_target": chosen[3].config_json["target"] if chosen else None,
        "inferred_channels": len(inference_features) if chosen else 0,
        "note": "Model chấm cả tiếp cận và từng hop hợp lệ. Tuyến trùng baseline vẫn là kết quả dùng FL; chưa chứng minh cải thiện độ trễ ứng dụng."}
    if distributed_model:
        result["runtime"]="federated-http-v3"
        result["allocation_policy"]=chosen[0].config_json.get("allocation_policy","deadline")
        result["model_applicability_note"]="Inference cold start nếu chưa có lịch sử tương thích; telemetry ứng dụng là mô phỏng, chưa xác nhận đo thực địa."
    if chosen:
        trained = set((chosen[0].config_json or {}).get("candidate_pool", []))
        result["model_applicability"] = {
            "training_target": chosen[3].config_json.get("target"),
            "training_payload_bytes": chosen[3].config_json["payload_bytes"],
            "application_payload_bytes": APPLICATION_PROFILES[request.service]["payload_bytes"],
            "route_nodes_outside_training_pool": [key for key in best["path"] if key not in trained],
            "held_out_fl_mae_ms": chosen[2].mae_ms,
            "routing_end_to_end_validated": False,
            "note": "Checkpoint học kênh client FL; áp dụng lên từng link/thiết bị là chuyển miền thử nghiệm. MAE holdout FL không chứng minh chất lượng định tuyến ứng dụng."}
    if chosen:
        trained_layers = {p["layer"] for p in chosen[3].config_json.get("profiles", {}).values()}
        result["unseen_layers"] = sorted({nodes[id].type for id in best["path"]} - trained_layers)
        result["comparison"] = {**result.get("comparison",{}), "same_path": best["path"] == baseline["path"],
                                "predicted_cost_change": baseline["total_predicted_transfer_ms"] - best["total_predicted_transfer_ms"],
                                "application_estimate_change_ms": result["baseline"]["application"]["estimated_one_way_ms"] - result["route"]["application"]["estimated_one_way_ms"],
                                "score_change": baseline["cost"] - best["cost"],
                                "evaluation_source": "same_snapshot_simulator_estimates_not_measured_improvement"}
    demand = profile["min_bandwidth"]
    result["allocation"] = {
        "reserved_mbps": demand, "other_event_count": reservations.get("event_count", 0),
        "policy": "Giữ băng thông các điểm đang tồn tại; chọn tuyến có tổng điểm thấp nhất trên phần còn lại. Không giành lại băng thông của tuyến cũ.",
        "nodes": [{"node_id": node_id, "reserved_before_mbps": used_nodes.get(node_id, 0.),
                   "available_before_mbps": node_capacity(nodes[node_id], selected_load),
                   "remaining_after_mbps": max(0., node_capacity(nodes[node_id], selected_load) - demand)} for node_id in best["path"]],
        "links": [{"source": hop["source"], "target": hop["target"],
                   "reserved_before_mbps": used_links.get(tuple(sorted((hop["source"], hop["target"]))), 0.),
                   "available_before_mbps": hop["bandwidth_mbps"],
                   "remaining_after_mbps": max(0., hop["bandwidth_mbps"] - demand)} for hop in best["hops"]],
    }
    if research:
        from backend.services.research_evaluation_service import evaluate_routes
        evaluate_routes(result,research,nodes,size,event,selected_load,chosen is not None)
    return result


def route_event(db, request, reservations=None):
    reservations = reservations or {}
    def snapshot(db, request, position_overrides=None, ingress_ids=None):
        overrides = {**reservations.get("positions", {}), **(position_overrides or {})}
        return route_snapshot(db, request, overrides, ingress_ids, reservations)

    result = snapshot(db, request)
    if request.routing_scope == "local" or region_for(db,request.scenario_id):
        return result  # A missing local route never triggers a remote deployment.
    if not request.allow_reposition or result.get("code") not in {"no_coverage", "no_path"}:
        return result
    from backend.services.mobility_service import reposition_route
    return reposition_route(db, request, result, snapshot,
                            unavailable_node_ids=set(reservations.get("nodes", {})) | reservations.get("locked_nodes", set()))
