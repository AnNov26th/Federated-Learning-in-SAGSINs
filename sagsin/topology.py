"""Explicit research graph; links are assumed engineered, not RF predictions."""
from dataclasses import asdict, dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class Node:
    id: str
    layer: str
    x: float
    y: float


@dataclass(frozen=True)
class Link:
    id: str
    source: str
    target: str
    capacity_mbps: float
    propagation_ms: float
    distance_km: float


NODES = [
    Node("G1", "GROUND", 100, 390), Node("G2", "GROUND", 370, 390),
    Node("G3", "GROUND", 650, 390), Node("EDGE", "GROUND", 920, 390),
    Node("A1", "AIR", 230, 240), Node("A2", "AIR", 520, 240), Node("A3", "AIR", 800, 240),
    Node("S1", "SPACE", 230, 80), Node("S2", "SPACE", 520, 80), Node("S3", "SPACE", 800, 80),
    Node("SEA1", "SEA", 230, 540), Node("SEA2", "SEA", 650, 540),
]


def make_links():
    specs = [
        ("G1", "G2", 40, 2, 40), ("G2", "G3", 30, 3, 70), ("G3", "EDGE", 40, 2, 40),
        ("G1", "A1", 18, 3, 20), ("A1", "A2", 15, 4, 60), ("A2", "A3", 15, 4, 60),
        ("A3", "EDGE", 18, 3, 20), ("G2", "A2", 20, 2, 20), ("G3", "A3", 20, 2, 20),
        ("A1", "S1", 10, 9, 650), ("S1", "S2", 12, 7, 1200),
        ("S2", "S3", 12, 7, 1200), ("S3", "A3", 10, 9, 650),
        ("SEA1", "G1", 12, 4, 80), ("SEA1", "A1", 9, 5, 100),
        ("SEA2", "G3", 12, 4, 80), ("SEA2", "S2", 8, 10, 700),
    ]
    return [Link(f"L{i:02}", *row) for i, row in enumerate(specs)]


LINKS = make_links()
BY_LINK = {link.id: link for link in LINKS}
BY_NODE = {node.id: node for node in NODES}


def configure(snapshot):
    """Install an immutable experiment snapshot in this execution process.

    Called only under the coordinator training lock, or during child startup.
    Mutate containers in place so imports in routing/dataset share the snapshot.
    """
    if snapshot is None:
        return
    nodes = [Node(**n) for n in snapshot["nodes"]]
    links = [Link(**e) for e in snapshot["links"]]
    known = {n.id for n in nodes}
    if not nodes or len(known) != len(nodes) or len({e.id for e in links}) != len(links):
        raise ValueError("Invalid topology identities")
    if any(n.layer not in {"SPACE", "AIR", "GROUND", "SEA"} for n in nodes):
        raise ValueError("Invalid topology layer")
    if any(e.source not in known or e.target not in known or e.source == e.target or
           not all(math.isfinite(v) for v in (e.capacity_mbps,e.propagation_ms,e.distance_km)) or
           e.capacity_mbps <= 0 or min(e.propagation_ms,e.distance_km) < 0 for e in links):
        raise ValueError("Invalid topology links")
    NODES[:] = nodes
    LINKS[:] = links
    BY_NODE.clear(); BY_NODE.update({n.id:n for n in nodes})
    BY_LINK.clear(); BY_LINK.update({e.id:e for e in links})


def stable_seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def channel(link, tick, seed, profile="mixed"):
    """Exogenous trace independent of routing actions; deterministic per link/time."""
    index = int(link.id[1:]) if link.id.startswith("L") and link.id[1:].isdigit() else stable_seed(link.id) % 1000
    base = {"normal": 0.22, "mixed": 0.42, "congested": 0.65}[profile]
    oscillation = 0.16 * math.sin(tick / (5 + index % 4) + index * 0.9)
    regime = 0.18 if (tick // 18 + index) % 4 == 1 else -0.04
    noise = random.Random(stable_seed(seed, link.id, tick)).uniform(-0.018, 0.018)
    load = min(0.94, max(0.04, base + oscillation + regime + noise))
    # A ground backbone outage exercises alternate paths in routing evaluation.
    outage_link = link.id == "L01" or (link.id.startswith("A") and index % 29 == 1)
    active = not (profile != "normal" and outage_link and 25 <= tick % 80 < 36)
    capacity = link.capacity_mbps * (1 - load) if active else 0.0
    queue_ms = 3.0 * load / (1 - load)
    return {"available_mbps": capacity, "load": load, "queue_ms": queue_ms, "active": active}


def reference_delay(link, tick, payload_bytes, seed, profile):
    c = channel(link, tick, seed, profile)
    # Training excludes outages; disconnected edges are masked before inference.
    rate = max(0.05, link.capacity_mbps * (1 - c["load"]))
    return link.propagation_ms + c["queue_ms"] + payload_bytes * 8 / (rate * 1000)


def public_topology():
    return {"nodes": [asdict(n) for n in NODES], "links": [asdict(e) for e in LINKS],
            "assumptions": "Engineered undirected snapshot links; fluid traffic; no orbital/RF simulation."}
