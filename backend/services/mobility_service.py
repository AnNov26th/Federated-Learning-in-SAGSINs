"""Temporary relay placement, travel estimates and routing; never updates DB nodes.

Speeds and free great-circle steering are demonstration assumptions, not orbital
mechanics, flight planning, or navigable sea routes. FL scores channel RTT, not
travel time. A small finite set of candidate placements is compared explicitly.
"""
import math
from types import SimpleNamespace

from backend.models.network import Node
from backend.services.routing_service import ACCESS_LIMITS_KM, SERVICES, finite, surface_distance

SPEED_KM_S = {"SPACE": 7.5, "AIR": .07, "SEA": .015}
R = 6371.


def interpolate(a, b, fraction):
    def vector(p):
        lat, lng = math.radians(p.lat), math.radians(p.lng)
        return (math.cos(lat)*math.cos(lng), math.cos(lat)*math.sin(lng), math.sin(lat))
    first, second = vector(a), vector(b)
    dot = max(-1., min(1., sum(x*y for x, y in zip(first, second))))
    angle = math.acos(dot)
    if angle < 1e-10:
        return {"lat": a.lat, "lng": a.lng}
    if math.pi-angle < 1e-7:
        # Pick a deterministic great circle for antipodal endpoints.
        axis = (0., 0., 1.) if abs(first[2]) < .9 else (1., 0., 0.)
        projection = sum(x*y for x, y in zip(axis, first))
        tangent = tuple(x-projection*y for x, y in zip(axis, first))
        length = math.sqrt(sum(v*v for v in tangent))
        point = tuple(x*math.cos(angle*fraction)+y/length*math.sin(angle*fraction) for x, y in zip(first, tangent))
    else:
        point = tuple((math.sin((1-fraction)*angle)*x+math.sin(fraction*angle)*y)/math.sin(angle) for x, y in zip(first, second))
    return {"lat": math.degrees(math.atan2(point[2], math.hypot(point[0], point[1]))),
            "lng": math.degrees(math.atan2(point[1], point[0]))}


def footprint(node, slant_limit):
    altitude = max(0., float(node.alt))
    if altitude <= 0:
        return slant_limit
    if slant_limit <= altitude:
        return 0.
    horizon = math.acos(R/(R+altitude))
    cosine = (R*R+(R+altitude)**2-slant_limit**2)/(2*R*(R+altitude))
    return R*min(horizon, math.acos(max(-1., min(1., cosine))))*.98


def movement(node, destination, boost):
    point = SimpleNamespace(**destination)
    distance = surface_distance(node, point)*(R+max(0, node.alt))/R
    speed = SPEED_KM_S[node.type]*boost
    return {"node_id": node.id, "type": node.type,
            "from": {"lat": node.lat, "lng": node.lng, "alt": node.alt},
            "to": {**destination, "alt": node.alt}, "distance_km": distance,
            "base_speed_km_s": SPEED_KM_S[node.type], "speed_km_s": speed,
            "boost": boost, "eta_s": distance/speed}


def reposition_route(db, request, original, snapshot, unavailable_node_ids=None):
    nodes = [n for n in db.query(Node).filter(Node.scenario_id == request.scenario_id,
             Node.status.ilike("ACTIVE")).order_by(Node.id)
             if finite(n.bandwidth, True) and finite(n.latency)]
    demand = request.required_bandwidth_mbps or SERVICES[request.service]["min_bandwidth"]
    mobile = [n for n in nodes if n.type in SPEED_KM_S and n.bandwidth >= demand
              and n.id not in (unavailable_node_ids or set())]
    grounds = [n for n in nodes if n.type == "GROUND" and n.bandwidth >= demand]
    origin = SimpleNamespace(lat=request.lat, lng=request.lng, alt=0.)
    plans = {}
    def add(moves, ingress):
        key = tuple((m["node_id"], round(m["to"]["lat"], 6), round(m["to"]["lng"], 6)) for m in moves)
        plans[key] = {"moves": moves, "ingress": ingress,
                      "eta_s": max(m["eta_s"] for m in moves)}
    # Candidate intersections of the event footprint and a GROUND backhaul.
    for node in mobile:
        access_limit = ACCESS_LIMITS_KM[node.type]
        if request.access_radius_km is not None:
            access_limit = min(access_limit, request.access_radius_km)
        reach = footprint(node, access_limit)
        backbone = footprint(node, 5000 if node.type == "SPACE" else 1500 if node.type == "AIR" else 500)
        if reach <= 0 or backbone <= 0:
            continue
        for ground in grounds:
            distance = surface_distance(origin, ground)
            low, high = max(0., distance-backbone), min(reach, distance)
            if low > high:
                continue
            for offset in {low, high, (low+high)/2, min(high, max(low, surface_distance(origin, node)))}:
                destination = interpolate(origin, ground, offset/distance if distance else 0)
                add([movement(node, destination, request.mobility_boost)], {node.id})
    # Ocean/antipodal fallback: position a chain using existing SPACE resources.
    # This avoids inventing an unbounded event-to-GROUND channel.
    satellites = [n for n in mobile if n.type == "SPACE" and n.alt > 0]
    if satellites:
        reach = min(footprint(n, min(5000, request.access_radius_km or 5000)) for n in satellites)
        max_alt = max(n.alt for n in satellites)
        span = min(2*reach, 5000*R/(R+max_alt))*.9
        if span > 0:
            for ground in grounds:
                distance = surface_distance(origin, ground)
                count = max(1, math.ceil(distance/span))
                if count > len(satellites):
                    continue
                available, moves = list(satellites), []
                for index in range(count):
                    destination = interpolate(origin, ground, (index+.5)/count)
                    chosen = min(available, key=lambda n: movement(n, destination, request.mobility_boost)["eta_s"])
                    moves.append(movement(chosen, destination, request.mobility_boost))
                    available.remove(chosen)
                add(moves, {moves[0]["node_id"]})
    best, best_score, checked = None, math.inf, 0
    for plan in sorted(plans.values(), key=lambda p: (p["eta_s"], len(p["moves"]))):
        # Nonnegative route costs make ETA a lower bound for this objective.
        if plan["eta_s"] > best_score:
            break
        overrides = {m["node_id"]: m["to"] for m in plan["moves"]}
        result = snapshot(db, request, overrides, plan["ingress"])
        checked += 1
        if result.get("code") in {"no_model", "invalid_prediction", "invalid_target"}:
            return {**result, "mobility_preview": {"moves": plan["moves"], "eta_s": plan["eta_s"]}}
        if result.get("status") != "routed":
            continue
        score = plan["eta_s"]+result["route"]["cost"]/1000
        if score < best_score:
            best_score = score
            result["mobility"] = {"required": True, "eta_s": plan["eta_s"], "moves": plan["moves"],
                "score_s": score, "candidate_count": len(plans),
                "objective": "travel_wait_seconds + selected_route_cost / 1000",
                "note": "Di chuyển theo cung cầu và tốc độ giả định; chưa mô phỏng động lực học quỹ đạo, nhiên liệu hay hải trình. FL chỉ dự đoán RTT kênh. Vị trí mới chỉ dùng trong lượt mô phỏng, không ghi database."}
            result["reason"] = "Đã chọn phương án điều động để tạo vùng phủ và đường về GROUND."
            best = result
    if best:
        best["mobility"]["evaluated_candidates"] = checked
        return best
    return {**original, "code": "mobility_unavailable",
            "reason": "Chưa có phương án điều động khả thi với phương tiện ACTIVE, băng thông và topology hiện tại. Cần thêm vệ tinh/UAV/tàu hoặc bổ sung backhaul tới GROUND.",
            "mobility": {"required": True, "moves": [], "candidate_count": len(plans), "evaluated_candidates": checked}}
