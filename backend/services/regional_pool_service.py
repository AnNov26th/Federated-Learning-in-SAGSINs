"""Deterministic geographic FL cohorts at database-position snapshots.

Distance is ground-projected great-circle distance, not an RF link or a route.
A radius constrains every member to the center; pairs can be up to 2R apart.
"""
import math


def ground_distance(first_lat, first_lng, second_lat, second_lng):
    lat1, lat2 = math.radians(first_lat), math.radians(second_lat)
    dlat = lat2-lat1
    dlng = math.radians(second_lng-first_lng)
    hav = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
    return 12742*math.asin(min(1., math.sqrt(max(0., hav))))


def choose_region(nodes, mode="regional", radius_km=1500., lat=None, lng=None):
    ordered = sorted(nodes, key=lambda node: node.id)
    if (lat is None) != (lng is None):
        raise ValueError("Provide both region latitude and longitude, or leave both empty for automatic selection.")
    if mode == "all":
        return ordered, {"mode":"all", "eligible_clients":len(ordered), "client_count":len(ordered)}
    if mode != "regional" or not math.isfinite(radius_km) or not 0 < radius_km <= 20040:
        raise ValueError("Invalid regional pool settings.")
    if not ordered:
        return [], {"mode":"regional", "radius_km":radius_km, "client_count":0, "eligible_clients":0}
    if lat is None:
        # Prefer a ground-centered area if ground nodes are eligible. Select the
        # densest area, resolving equal counts by anchor ID, never by future labels.
        anchors = [node for node in ordered if node.type == "GROUND"] or ordered
        choices = []
        for anchor in anchors:
            members = [node for node in ordered if ground_distance(anchor.lat,anchor.lng,node.lat,node.lng) <= radius_km+1e-9]
            choices.append((-len(members), anchor.id, anchor, members))
        _, _, center, selected = min(choices, key=lambda item: (item[0],item[1]))
        lat, lng, anchor_id, source = center.lat, center.lng, center.id, "densest_eligible_snapshot_area"
    else:
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Invalid region coordinates.")
        selected = [node for node in ordered if ground_distance(lat,lng,node.lat,node.lng) <= radius_km+1e-9]
        anchor_id, source = None, "explicit_center"
    distances = {node.id: ground_distance(lat,lng,node.lat,node.lng) for node in selected}
    return selected, {"mode":"regional", "center_lat":lat, "center_lng":lng, "radius_km":radius_km,
        "anchor_id":anchor_id, "selection_source":source, "eligible_clients":len(ordered), "client_count":len(selected),
        "max_center_distance_km":max(distances.values(),default=0.), "distances_km":distances,
        "distance_definition":"ground_projected_great_circle_at_database_snapshot",
        "note":"Geographic cohort only; membership does not prove RF links or reachability to an FL aggregator."}
