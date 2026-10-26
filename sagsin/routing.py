import heapq
from .dataset import feature_row
from .model import predictions
from .topology import LINKS, BY_LINK, BY_NODE, channel


def edge_costs(tick, config, policy, model=None):
    if policy not in {"static", "current", "fl"}:
        raise ValueError("Unknown routing policy")
    active = [e for e in LINKS if channel(e, tick, config.seed, config.profile)["active"]]
    rows = [feature_row(e, BY_NODE[e.source].layer, tick, config.seed,
                        config.profile, config.payload_bytes) for e in active]
    if policy == "fl":
        if model is None:
            raise ValueError("FL routing requires a compatible model")
        values = predictions(model, rows)
    elif policy == "current":
        values = [row["observed_delay_ms"] for row in rows]
    else:
        values = [e.propagation_ms + config.payload_bytes * 8 / (e.capacity_mbps * 1000) for e in active]
    return {e.id: max(0.001, value) for e, value in zip(active, values)}


def shortest_path(source, destination, costs):
    if source not in BY_NODE or destination not in BY_NODE:
        raise ValueError("Unknown endpoint")
    adjacency = {node: [] for node in BY_NODE}
    for edge_id, cost in costs.items():
        if cost < 0:
            raise ValueError("Negative edge cost")
        e = BY_LINK[edge_id]
        adjacency[e.source].append((e.target, e.id, cost))
        adjacency[e.target].append((e.source, e.id, cost))
    queue = [(0.0, source, [], [source])]
    best = {source: 0.0}
    while queue:
        cost, node, links, nodes = heapq.heappop(queue)
        if cost > best[node]:
            continue
        if node == destination:
            return {"links": links, "nodes": nodes, "cost_ms": cost}
        for neighbor, edge, weight in adjacency[node]:
            candidate = cost + weight
            if candidate < best.get(neighbor, float("inf")):
                best[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor, links + [edge], nodes + [neighbor]))
    return None
