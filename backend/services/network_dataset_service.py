"""Reproducible temporal telemetry generated from immutable topology snapshots."""
import hashlib
import json
import math
import random
from collections import Counter

from backend.algorithms.network_delay_model import FEATURE_VERSION, payload_bytes
from backend.models.network import NetworkLink, Node
from backend.models.network_learning import NetworkDataset, NetworkObservation
from backend.services.delay_service import NETWORK_PROFILES, estimate_communication_ms

GENERATOR_VERSION = "sagsin-network-v1"
ONLINE_STEPS = 100


def stable_seed(seed, client_id, purpose):
    return int.from_bytes(hashlib.sha256(f"{seed}:{client_id}:{purpose}".encode()).digest()[:4], "big")


def create_dataset(db, scenario_id, seed=42, samples_per_client=160, partition="non_iid", network_profile="normal"):
    nodes = db.query(Node).filter(Node.scenario_id == scenario_id, Node.status == "ACTIVE").order_by(Node.id).all()
    if len(nodes) < 2:
        raise ValueError("At least two ACTIVE scenario nodes are required to generate network data.")
    if not 40 <= samples_per_client <= 2000:
        raise ValueError("samples_per_client must be between 40 and 2000.")
    if partition not in {"iid", "non_iid"} or network_profile not in NETWORK_PROFILES:
        raise ValueError("Unsupported partition or network profile.")
    node_ids = {node.id for node in nodes}
    links = db.query(NetworkLink).filter(NetworkLink.status == "ACTIVE").order_by(NetworkLink.id).all()
    snapshots = {}
    for node in nodes:
        incident = [link for link in links if node.id in {link.source, link.target} and link.source in node_ids and link.target in node_ids]
        # A representative incident link is not an inferred multi-hop route.
        link = min(incident, key=lambda item: (item.latency, item.id)) if incident else None
        distance = max(0., float(link.distance) if link else float(node.alt or 0))
        snapshots[node.id] = {
            "layer": str(node.type).upper(), "status": node.status,
            "latency": max(float(node.latency or 0), float(link.latency) if link else 0, distance / 299.792458),
            "bandwidth": max(.01, min(float(node.bandwidth or .01), float(link.bandwidth) if link else float(node.bandwidth or .01))),
            "distance_km": distance, "medium": "radio_frequency",
            "link_id": link.id if link else None,
            "link_source": "stored_incident_link" if link else "synthetic_client_server_channel",
        }
    config = {
        "samples_per_client": samples_per_client, "partition": partition,
        "network_profile": network_profile, "online_steps": ONLINE_STEPS,
        "payload_bytes": payload_bytes(), "feature_version": FEATURE_VERSION,
        "source": "generated", "target": "next_tick_model_round_trip_ms",
        "profiles": snapshots,
        "split_order": ["train", "validation", "online", "test"],
        "locality": "logical_client_partitions_in_shared_database",
    }
    material = json.dumps({"seed": seed, "version": GENERATOR_VERSION, "config": config}, sort_keys=True)
    dataset = NetworkDataset(scenario_id=scenario_id, seed=seed, generator_version=GENERATOR_VERSION,
                             fingerprint=hashlib.sha256(material.encode()).hexdigest(), config_json=config)
    db.add(dataset)
    db.flush()
    profile = NETWORK_PROFILES[network_profile]
    typical = {
        "latency": sum(value["latency"] for value in snapshots.values()) / len(nodes),
        "bandwidth": sum(value["bandwidth"] for value in snapshots.values()) / len(nodes),
        "distance_km": sum(value["distance_km"] for value in snapshots.values()) / len(nodes),
    }
    train_count = int(samples_per_client * .6)
    validation_count = int(samples_per_client * .2)
    test_count = samples_per_client - train_count - validation_count
    # Gaps keep labels at t+1 inside their own temporal split.
    ranges = [
        ("train", 0, train_count),
        ("validation", train_count + 1, validation_count),
        ("online", train_count + validation_count + 2, ONLINE_STEPS),
        ("test", train_count + validation_count + ONLINE_STEPS + 3, test_count),
    ]
    total_ticks = ranges[-1][1] + test_count + 1
    records = []
    for node in nodes:
        snapshot = snapshots[node.id]
        base = snapshot if partition == "non_iid" else typical
        rng = random.Random(stable_seed(seed, node.id, "telemetry"))
        phase = rng.uniform(0, math.tau)
        load = rng.uniform(.1, .7)
        series = []
        for tick in range(total_ticks):
            cycle = .35 + .25 * math.sin(tick / 13 + phase)
            load = min(.94, max(.03, .8 * load + .2 * cycle + rng.gauss(0, .06)))
            latency = max(.01, base["latency"] * profile["latency_multiplier"] * (1 + .8 * load) + 25 * load ** 2)
            bandwidth = max(.01, base["bandwidth"] * profile["bandwidth_multiplier"] * (1 - .65 * load))
            loss = min(.15, .04 * load ** 2)
            communication = estimate_communication_ms(latency, bandwidth, payload_bytes() / (1024 * 1024)) / (1 - loss)
            series.append({
                "layer": snapshot["layer"], "latency_ms": latency,
                "bandwidth_mbps": bandwidth, "distance_km": base["distance_km"],
                "load_ratio": load, "packet_loss_ratio": loss,
                "jitter_ms": abs(rng.gauss(0, max(.01, latency * .04))),
                "payload_bytes": payload_bytes(), "observed_delay_ms": communication,
            })
        for split, start, count in ranges:
            for tick in range(start, start + count):
                records.append(NetworkObservation(dataset_id=dataset.id, client_id=node.id, sequence=tick,
                                                   split=split, features_json=series[tick],
                                                   target_delay_ms=series[tick + 1]["observed_delay_ms"]))
    db.add_all(records)
    db.flush()
    return dataset


def dataset_summary(db, dataset):
    from sqlalchemy import func
    counts = db.query(NetworkObservation.split, func.count(NetworkObservation.id)).filter(
        NetworkObservation.dataset_id == dataset.id).group_by(NetworkObservation.split).all()
    config = dataset.config_json
    return {
        "id": dataset.id, "scenario_id": dataset.scenario_id, "seed": dataset.seed,
        "generator_version": dataset.generator_version, "fingerprint": dataset.fingerprint,
        "source": "generated", "target": config["target"], "partition": config["partition"],
        "network_profile": config["network_profile"], "client_count": len(config["profiles"]),
        "counts": dict(counts), "layers": dict(Counter(p["layer"] for p in config["profiles"].values())),
        "locality": config["locality"], "created_at": dataset.created_at,
    }
