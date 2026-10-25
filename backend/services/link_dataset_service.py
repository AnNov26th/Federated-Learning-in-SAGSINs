"""Per-client outgoing-link observations with chronological, disjoint labels."""

import hashlib
import json
import math
from backend.algorithms.network_delay_model import FEATURE_VERSION, payload_bytes
from backend.models.network import Node, NetworkLink
from backend.models.network_learning import NetworkDataset, NetworkObservation
from backend.services.link_telemetry_service import LINK_TARGET, telemetry


def create_link_dataset(
    db,
    scenario_id,
    seed,
    samples_per_client,
    partition,
    network_profile,
    online_steps,
    client_ids=None,
):
    from backend.services.research_region_service import region_for
    if not region_for(db,scenario_id):
        raise ValueError("Application-link training requires an explicit research region.")
    if partition != "non_iid":
        raise ValueError(
            "Link telemetry uses explicit local outgoing-link partitions; select non_iid."
        )
    nodes = (
        db.query(Node)
        .filter_by(scenario_id=scenario_id, status="ACTIVE")
        .order_by(Node.id)
        .all()
    )
    if client_ids is not None:
        nodes = [node for node in nodes if node.id in client_ids]
    if len(nodes) < 2 or samples_per_client < 40 or online_steps < 1:
        raise ValueError(
            "At least 2 clients, 40 historical samples and 1 online tick are required."
        )
    by_id = {node.id: node for node in nodes}
    links = [
        link
        for link in db.query(NetworkLink)
        .filter_by(status="ACTIVE")
        .order_by(NetworkLink.id)
        if link.source in by_id and link.target in by_id
    ]
    outgoing = {key: [] for key in by_id}
    snapshots = {}
    for link in links:
        item = {
            key: getattr(link, key)
            for key in ("id", "source", "target", "bandwidth", "latency", "distance")
        }
        outgoing[link.source].append((item, link.target))
        outgoing[link.target].append((item, link.source))
    if any(not value for value in outgoing.values()):
        raise ValueError(
            "Each link-learning client needs at least one explicit ACTIVE incident link in the selected pool."
        )
    for node in nodes:
        snapshots[node.id] = {
            "layer": node.type,
            "status": node.status,
            "latency": node.latency,
            "bandwidth": node.bandwidth,
            "links": [row[0]["id"] for row in outgoing[node.id]],
        }
    config = {
        "samples_per_client": samples_per_client,
        "online_steps": online_steps,
        "partition": partition,
        "network_profile": network_profile,
        "payload_bytes": payload_bytes(),
        "feature_version": FEATURE_VERSION,
        "source": "generated",
        "target": LINK_TARGET,
        "profiles": snapshots,
        "application_payloads": [256, 1024, 1200, 4096, 65536],
        "link_snapshot": [
            {
                key: getattr(link, key)
                for key in (
                    "id",
                    "source",
                    "target",
                    "distance",
                    "latency",
                    "bandwidth",
                )
            }
            for link in links
        ],
        "split_order": ["train", "validation", "online", "test"],
        "locality": "outgoing_link_telemetry_partitioned_by_source_node",
        "label_unit": "one_way_ms",
        "channel_model": "shared_fluid_queue_v1",
        "seed": seed,
    }
    material = json.dumps(config, sort_keys=True)
    dataset = NetworkDataset(
        scenario_id=scenario_id,
        seed=seed,
        generator_version="sagsin-application-link-v1",
        fingerprint=hashlib.sha256(material.encode()).hexdigest(),
        config_json=config,
    )
    db.add(dataset)
    db.flush()
    train = int(samples_per_client * 0.6)
    validation = int(samples_per_client * 0.2)
    test = samples_per_client - train - validation
    ranges = [
        ("train", 0, train),
        ("validation", train + 1, validation),
        ("online", train + validation + 2, online_steps),
        ("test", train + validation + online_steps + 3, test),
    ]
    records = []
    for index, node in enumerate(nodes):
        for split, start, count in ranges:
            for sequence in range(start, start + count):
                link, target = outgoing[node.id][sequence % len(outgoing[node.id])]
                payload = config["application_payloads"][
                    (sequence // len(outgoing[node.id])) % 5
                ]
                # Per-link/per-client phases, changing background load. t+1
                # remains inside each split; no future state is an input.
                level = 0.45 + 0.35 * math.sin(
                    sequence / 37 + (seed % 71) + index * 0.7
                )
                next_level = 0.45 + 0.35 * math.sin(
                    (sequence + 1) / 37 + (seed % 71) + index * 0.7
                )
                if network_profile == "low_bandwidth":
                    scale = 0.1
                else:
                    scale = 1.0
                if network_profile == "high_latency":
                    link = {**link, "latency": link["latency"] * 10}
                if network_profile == "bursty_congestion":
                    level = 0.95 if sequence % 47 < 8 else level
                    next_level = 0.95 if (sequence + 1) % 47 < 8 else next_level
                elif network_profile == "regime_switching":
                    level = min(0.97, level + 0.2 * (sequence // 60 % 2))
                    next_level = min(
                        0.97, next_level + 0.2 * ((sequence + 1) // 60 % 2)
                    )
                features = telemetry(
                    link,
                    by_id[target].type,
                    sequence,
                    payload,
                    level,
                    capacity_scale=scale,
                )
                features.update(source=node.id, target=target)
                label = telemetry(
                    link,
                    by_id[target].type,
                    sequence + 1,
                    payload,
                    next_level,
                    capacity_scale=scale,
                )["observed_delay_ms"]
                records.append(
                    dict(
                        dataset_id=dataset.id,
                        client_id=node.id,
                        sequence=sequence,
                        split=split,
                        features_json=features,
                        target_delay_ms=label,
                    )
                )
                if len(records) >= 2000:
                    db.execute(NetworkObservation.__table__.insert(), records)
                    records.clear()
    if records:
        db.execute(NetworkObservation.__table__.insert(), records)
    return dataset
