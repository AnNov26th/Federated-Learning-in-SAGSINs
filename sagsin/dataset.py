"""Client-local chronological MySQL datasets and deterministic telemetry."""
import json
import hashlib
import random
from .database import connect
from .config import ExperimentConfig
from .topology import LINKS, BY_NODE, channel, reference_delay, stable_seed


def feature_row(link, layer, tick, seed, profile, payload):
    current = channel(link, tick, seed, profile)
    before = channel(link, tick - 1, seed, profile)
    observed = reference_delay(link, tick, payload, seed, profile)
    previous = reference_delay(link, tick - 1, payload, seed, profile)
    history_valid = before["active"]
    if not history_valid:
        previous = observed
        before = current
    return {"link_id": link.id, "tick": tick, "layer": layer, "history_valid": history_valid,
            "observed_delay_ms": observed, "previous_delay_ms": previous,
            "delta_delay_ms": observed - previous,
            "propagation_ms": link.propagation_ms, "distance_km": link.distance_km,
            "available_mbps": link.capacity_mbps * (1 - current["load"]),
            "load": current["load"], "load_before": before["load"],
            "delta_load": current["load"] - before["load"],
            "queue_ms": current["queue_ms"], "payload_bytes": payload}


def generate(client_id, config):
    incident = [link for link in LINKS if client_id in (link.source, link.target)]
    rng = random.Random(stable_seed(config.seed, client_id, "dataset"))
    links = LINKS if config.partition == "iid" else incident
    n = config.samples_per_client
    # Two-tick gaps prevent shared label/feature observations across split boundaries.
    boundaries = [("train", 2, int(n * .6) - 1),
                  ("validation", int(n * .6) + 2, int(n * .8) - 1),
                  ("test", int(n * .8) + 2, n - 1)]
    result = []
    for split, start, end in boundaries:
        for tick in range(start, end):
            link = rng.choice(links)
            if not channel(link, tick, config.seed, config.profile)["active"] or not channel(
                link, tick + 1, config.seed, config.profile)["active"]:
                continue
            layer = BY_NODE[link.source].layer if config.partition == "iid" else BY_NODE[client_id].layer
            row = feature_row(link, layer, tick, config.seed, config.profile, config.payload_bytes)
            row.update(split=split, client_id=client_id,
                       target_ms=reference_delay(link, tick + 1, config.payload_bytes, config.seed, config.profile))
            result.append(row)
    return result


def save_local(settings, run_id, rows, config):
    encoded = [(row["split"], json.dumps(row, sort_keys=True, separators=(",", ":"))) for row in rows]
    fingerprint = hashlib.sha256("".join(value for _, value in encoded).encode()).hexdigest()
    with connect(settings) as db:
        with db.cursor() as cursor:
            cursor.execute("SELECT fingerprint, config_json FROM datasets WHERE run_id=%s", (run_id,))
            existing = cursor.fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint or ExperimentConfig.from_saved(json.loads(existing["config_json"])).model_dump() != ExperimentConfig.from_saved(config).model_dump():
                    raise ValueError("Existing client data differs; refusing to overwrite")
                return fingerprint
            cursor.executemany("INSERT INTO observations(run_id, split, payload) VALUES (%s,%s,%s)",
                               [(run_id, split, value) for split, value in encoded])
            cursor.execute("INSERT INTO datasets(run_id,fingerprint,config_json) VALUES (%s,%s,%s)",
                           (run_id, fingerprint, json.dumps(config, sort_keys=True)))
        db.commit()
    return fingerprint


def load_local(settings, run_id, split):
    with connect(settings) as db:
        with db.cursor() as cursor:
            cursor.execute("SELECT payload FROM observations WHERE run_id=%s AND split=%s ORDER BY id", (run_id, split))
            return [json.loads(row["payload"]) for row in cursor.fetchall()]
