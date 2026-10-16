"""Auditable FL-assisted routing on a database topology snapshot.

The saved regressor predicts next-tick FL-payload round trips. Applying that
regressor to individual hops is an experimental routing surrogate, NOT a
prediction of application latency. No held-out labels enter routing decisions.
"""
import heapq
import math
from datetime import datetime, timezone

from backend.algorithms.network_delay_model import FEATURE_VERSION, load_checkpoint, payload_bytes, predict
from backend.models.network import NetworkLink, Node
from backend.models.network_learning import NetworkDataset, NetworkRoundEvaluation
from backend.models.simulation import Experiment, FLRound
from backend.services.delay_service import NETWORK_PROFILES, estimate_communication_ms


SERVICES = {
    "Message": {"latency_weight": .55, "capacity_weight": .1, "min_bandwidth": .05},
    "Video Call": {"latency_weight": .45, "capacity_weight": .4, "min_bandwidth": 2},
    "Watch Video": {"latency_weight": .2, "capacity_weight": .75, "min_bandwidth": 5},
    "Gaming": {"latency_weight": .8, "capacity_weight": .08, "min_bandwidth": 1},
    "Emergency": {"latency_weight": 1, "capacity_weight": .15, "min_bandwidth": .1},
}
MODEL_NOTE = (
    "Model FL dự đoán RTT của payload huấn luyện ở tick tiếp theo. Tổng dự đoán "
    "từng hop là chỉ số thay thế để xếp hạng tuyến, chưa được kiểm chứng cho "
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
    # Ground access uses an explicit coverage radius; elevated radio channels
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
        if dataset.config_json.get("feature_version") != FEATURE_VERSION or dataset.config_json.get("target") != "next_tick_model_round_trip_ms":
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


def route_event(db, request):
    profile = SERVICES[request.service]
    result = {"status": "unavailable", "reason": "", "route": None, "baseline": None,
              "policy": request.policy, "topology": request.topology, "model": None,
              "snapshot_at": datetime.now(timezone.utc).isoformat(), "note": MODEL_NOTE,
              "profile": profile, "scenario_id": request.scenario_id}
    def fail(code, reason):
        return {**result, "code": code, "reason": reason}

    nodes = {n.id: n for n in db.query(Node).filter(Node.scenario_id == request.scenario_id, Node.status.ilike("ACTIVE")).order_by(Node.id)
             if finite(n.bandwidth, True) and finite(n.latency) and n.type in {"GROUND", "AIR", "SPACE", "SEA"}}
    if not nodes:
        return fail("no_nodes", "Scenario chưa có node ACTIVE hợp lệ.")
    origin = type("Origin", (), {"lat": request.lat, "lng": request.lng, "alt": 0.})()
    coverage = sorted((channel_distance(origin, n) if n.alt > 0 else surface_distance(origin, n), n.id)
                      for n in nodes.values() if visible(origin, n))
    if not coverage or coverage[0][0] > request.access_radius_km:
        return fail("no_coverage", "Điểm sự kiện nằm ngoài bán kính tiếp cận hoặc dưới đường chân trời của node.")
    distance, source = coverage[0]
    result["access"] = {"source_id": source, "distance_km": distance, "radius_km": request.access_radius_km,
                        "latency_ms": distance / 299.792458, "is_estimated": True}
    targets = {n.id for n in nodes.values() if n.type == "GROUND" and n.id != source}
    if request.target_id:
        if request.target_id not in nodes or nodes[request.target_id].type != "GROUND":
            return fail("invalid_target", "Đích phải là node GROUND ACTIVE trong cùng scenario.")
        targets = {request.target_id}
    if not targets:
        return fail("no_target", "Cần node GROUND ACTIVE khác node tiếp cận làm đích.")

    chosen = None
    if request.policy == "predictive":
        candidates = model_candidates(db, request.scenario_id)
        chosen = next((c for c in candidates if c[0].id == request.experiment_id), None) if request.experiment_id else next(iter(candidates), None)
        if chosen is None:
            return fail("no_model", "Chưa có checkpoint FL hoàn tất phù hợp. Huấn luyện Network delay cho scenario này hoặc chọn công thức tĩnh.")
        result["model"] = model_summary(chosen)

    links = estimated_links(list(nodes.values())) if request.topology == "estimated" else [
        {key: getattr(link, key) for key in ("id", "source", "target", "distance", "latency", "bandwidth")}
        for link in db.query(NetworkLink).filter(NetworkLink.status.ilike("ACTIVE")).order_by(NetworkLink.id)
        if link.source in nodes and link.target in nodes]
    size = chosen[3].config_json["payload_bytes"] if chosen else payload_bytes()
    network_profile = NETWORK_PROFILES[chosen[3].config_json["network_profile"] if chosen else "normal"]
    source_capacity = nodes[source].bandwidth * network_profile["bandwidth_multiplier"] * (1 - .65 * request.load_ratio)
    if source_capacity < profile["min_bandwidth"]:
        return fail("no_path", f"Node tiếp cận {source} không đủ băng thông dịch vụ sau khi áp dụng tải.")
    edges, features = [], []
    excluded = 0
    for link in links:
        if not finite(link["bandwidth"], True) or not finite(link["latency"]) or not finite(link["distance"]):
            excluded += 1
            continue
        for first, second in ((link["source"], link["target"]), (link["target"], link["source"])):
            a, b = nodes[first], nodes[second]
            load = request.load_ratio
            bandwidth = min(a.bandwidth, b.bandwidth, link["bandwidth"]) * network_profile["bandwidth_multiplier"] * (1 - .65 * load)
            if bandwidth < profile["min_bandwidth"]:
                excluded += 1
                continue
            latency = max(a.latency, b.latency, link["latency"], link["distance"] / 299.792458) * network_profile["latency_multiplier"] * (1 + .8 * load) + 25 * load**2
            loss = .04 * load**2
            static = estimate_communication_ms(latency, bandwidth, size / (1024*1024)) / (1 - loss)
            feature = {"layer": b.type, "observed_delay_ms": static, "latency_ms": latency,
                       "bandwidth_mbps": bandwidth, "distance_km": link["distance"],
                       "load_ratio": load, "packet_loss_ratio": loss, "jitter_ms": latency*.04, "payload_bytes": size}
            features.append(feature)
            edges.append({"link_id": link["id"], "source": first, "target": second,
                          "bandwidth_mbps": bandwidth, "static_ms": static, "predicted_ms": None,
                          "features": feature})
    result["diagnostics"] = {"active_nodes": len(nodes), "links": len(links), "eligible_directions": len(edges), "excluded": excluded}
    if chosen and features:
        from backend.services.fl_service import _training_lock
        with _training_lock:
            predictions = predict(load_checkpoint(chosen[2].checkpoint_json), features)
        if len(predictions) != len(edges) or any(not finite(value) for value in predictions):
            return fail("invalid_prediction", "Model trả về dự đoán không hợp lệ; hãy kiểm tra checkpoint.")
        for edge, prediction in zip(edges, predictions):
            edge["predicted_ms"] = prediction
    baseline = shortest_route(source, targets, nodes, edges, profile, "static_ms", source_capacity)
    best = shortest_route(source, targets, nodes, edges, profile, "predicted_ms", source_capacity) if chosen else baseline
    if best is None:
        return fail("no_path", f"Không có tuyến từ {source} tới GROUND thỏa băng thông ≥ {profile['min_bandwidth']} Mbps. Kiểm tra link ACTIVE hoặc giảm tải.")
    def decorate(route):
        return {**route, "sourceId": source, "targetId": route["path"][-1],
                "accessDistanceKm": distance, "hop_count": len(route["hops"]),
                "positions": [{"id": id, "type": nodes[id].type, "lat": nodes[id].lat, "lng": nodes[id].lng, "alt": nodes[id].alt} for id in route["path"]]}
    result.update(status="routed", code="ok", reason="Đã chọn tuyến có tổng chi phí nhỏ nhất.",
                  route=decorate(best), baseline=decorate(baseline), payload_bytes=size,
                  objective="Σ(w_delay × RTT_proxy_ms + w_capacity × 100 / bandwidth_Mbps)")
    if chosen:
        trained_layers = {p["layer"] for p in chosen[3].config_json.get("profiles", {}).values()}
        result["unseen_layers"] = sorted({nodes[id].type for id in best["path"]} - trained_layers)
        result["comparison"] = {"same_path": best["path"] == baseline["path"],
                                "predicted_cost_change": baseline["predicted_transfer_ms"] - best["predicted_transfer_ms"]}
    return result
