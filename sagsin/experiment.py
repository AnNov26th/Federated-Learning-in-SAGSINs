"""Coordinator consumes model updates and aggregate metrics, never raw local rows."""
from collections import defaultdict
import hashlib
import math
from pathlib import Path
import random
import time
import torch
from .config import ExperimentConfig, FEATURE_VERSION, TARGET, SIMULATOR_VERSION
from .fedavg import FedAvg
from .model import DelayModel, envelope, metrics, validate_envelope
from .simulation import compare_network
from .storage import read_json, write_json
from .topology import NODES, BY_NODE, stable_seed, configure
from .transport import ClientPool

CLIENT_ORDER = ["G1", "A1", "S1", "SEA1", "G2", "A2", "S2", "SEA2", "G3", "A3", "S3", "EDGE"]


def combine(evaluations, key):
    available = [result for result in evaluations if key in result]
    layers = defaultdict(list)
    for result in available:
        layers[result["layer"]].append(result[key])
    return dict(metrics([r[key] for r in available]),
                by_layer={layer: metrics(values) for layer, values in layers.items()})


def run_experiment(config, directory, progress=lambda value: None, check_cancel=lambda: None, resume=False):
    torch.set_num_threads(1)
    torch.manual_seed(config.seed)
    configure(config.topology)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ids = config.client_ids or CLIENT_ORDER[:config.client_count]
    rounds = []
    epochs = {identifier: 0 for identifier in ids}
    model = DelayModel(config.model_family)
    initial = envelope(model)
    counters_before = {}
    if resume:
        saved = read_json(directory / "checkpoint.json")
        if ExperimentConfig.from_saved(saved["config"]).model_dump() != config.model_dump():
            raise ValueError("Cannot resume a checkpoint with different configuration")
        model = validate_envelope(saved["model"])
        rounds = saved["rounds"]
        epochs = saved["local_epochs"]
        initial = saved["initial_model"]
        counters_before = saved.get("communication", {})
    started = time.perf_counter()
    progress({"stage": "clients", "message": f"Khởi động {len(ids)} client độc lập"})
    with ClientPool(ids, config, directory / "clients", check_cancel) as pool:
        health = {identifier: pool.call(identifier, "/health") for identifier in ids}
        progress({"stage":"clients_ready","clients":health})
        for number in range(len(rounds) + 1, config.rounds + 1):
            check_cancel()
            progress({"stage": "training", "round": number, "message": f"Huấn luyện vòng {number}/{config.rounds}"})
            count = min(len(ids), config.clients_per_round or max(2, math.ceil(len(ids) * config.client_fraction)))
            rng = random.Random(stable_seed(config.seed, number, "selection"))
            if config.selection == "random":
                selected = rng.sample(ids, count)
            else:
                from .routing import edge_costs, shortest_path
                costs = edge_costs(number, config, "fl" if config.selection=="predictive" else "current",model)
                def delay(identifier):
                    target = (config.topology or {}).get("destination", "EDGE")
                    route = shortest_path(identifier, target, costs)
                    return route["cost_ms"] if route else float("inf")
                selected = sorted(ids, key=lambda c: (delay(c), c))[:count]
            dropped = [identifier for identifier in selected if rng.random() < config.dropout_probability]
            active = [identifier for identifier in selected if identifier not in dropped]
            progress({"stage":"local_training","round":number,"selected":selected})
            before = envelope(model)
            wall_started = time.perf_counter()
            replies = pool.parallel(active, "/train", {identifier: {"round": number, "model": before} for identifier in active}, "training")
            states, sizes, outcomes, updates = [], [], [], []
            for identifier in selected:
                if identifier in dropped:
                    outcomes.append({"client": identifier, "status": "dropped"})
                    continue
                response = replies[identifier]
                if not response["ok"]:
                    outcomes.append({"client": identifier, "status": "failed", "error": response["error"]})
                    continue
                value = response["result"]
                try:
                    local = validate_envelope(value["model"])
                    if local.family != model.family:
                        raise ValueError("Unexpected update model family")
                    if value["round"] != number or value["client_id"] != identifier or value["samples"] != health[identifier]["splits"]["train"]:
                        raise ValueError("Update identity, round or sample count mismatch")
                    states.append(local.state_dict())
                    sizes.append(value["samples"])
                    epochs[identifier] += config.local_epochs_by_client.get(identifier,config.local_epochs)
                    updates.append(value)
                    outcomes.append({"client": identifier, "status": "completed", "samples": value["samples"], "training_s": value["training_s"], "http_s":value.get("_http_elapsed_s",0),"local_epochs":config.local_epochs_by_client.get(identifier,config.local_epochs)})
                except (ValueError, KeyError, TypeError) as exc:
                    outcomes.append({"client": identifier, "status": "rejected", "error": str(exc)})
            if not states:
                raise RuntimeError(f"No valid model updates in round {number}")
            agg_started = time.perf_counter()
            model.load_state_dict(FedAvg.aggregate(states, sizes))
            aggregation_s = time.perf_counter() - agg_started
            round_s = time.perf_counter() - wall_started
            evaluations = pool.parallel(ids, "/evaluate", {identifier: {"model": envelope(model), "split": "validation"} for identifier in ids}, "validation")
            if any(not result["ok"] for result in evaluations.values()):
                raise RuntimeError("Incomplete validation; cannot report a fair metric")
            values = [r["result"] for r in evaluations.values()]
            record = {"round": number, "selected": selected, "clients": outcomes,
                      "validation": combine(values, "fl"), "persistence": combine(values, "persistence"),
                      "wall_s": round_s, "aggregation_s": aggregation_s}
            rounds.append(record)
            # Full updates permit mathematical FedAvg verification; they are sensitive model artifacts.
            write_json(directory / "audit" / f"round-{number:03}.json",
                       {"global_before": before, "updates": updates, "global_after": envelope(model)})
            cumulative = _counters(counters_before, pool.counters)
            write_json(directory / "checkpoint.json", {"config": config.model_dump(), "model": envelope(model),
                       "initial_model": initial, "rounds": rounds, "local_epochs": epochs, "communication": cumulative})
            progress({"stage": "training", "round": number, "rounds": rounds, "communication": cumulative,
                      "message": f"Vòng {number}: validation MAE {record['validation']['mae_ms']:.4f} ms"})
        check_cancel()
        progress({"stage": "evaluation", "message": "Đánh giá test tại client và baseline local-only"})
        evaluated = pool.parallel(ids, "/evaluate", {identifier: {"model": envelope(model), "split": "test",
                                 "local_epochs": epochs[identifier]} for identifier in ids}, "test")
        if any(not r["ok"] for r in evaluated.values()):
            raise RuntimeError("Incomplete test evaluation")
        values = [r["result"] for r in evaluated.values()]
        test = {key: combine(values, key) for key in ("fl", "persistence", "linear_trend", "moving_average", "local_only")}
        communication = _counters(counters_before, pool.counters)
    progress({"stage": "network", "message": "So sánh routing, Minimax và cấp phát theo deadline"})
    network = compare_network(config, model, check_cancel)
    for item in network:
        key = item["summary"]["route_policy"] + "-" + item["summary"]["allocation_policy"]
        write_json(directory / "network" / f"{key}.json", item)
    source_hash = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        source_hash.update(source.name.encode())
        source_hash.update(source.read_bytes())
    result = {"config": config.model_dump(), "versions": {"feature": FEATURE_VERSION, "target": TARGET,
              "implementation_sha256": source_hash.hexdigest(),
              "simulator": SIMULATOR_VERSION, "torch": torch.__version__},
              "clients": health, "rounds": rounds, "test": test,
              "startup_retries": pool.startup_retries,
              "network": [item["summary"] for item in network],
              "communication": {"categories": communication,
                   "codec":config.transport_codec,
                   "total_json_bytes": sum(v["sent_bytes"] + v["received_bytes"] for v in communication.values()),
                   "dense_equivalent_bytes":sum(v.get("dense_equivalent_sent_bytes",v["sent_bytes"])+v.get("dense_equivalent_received_bytes",v["received_bytes"]) for v in communication.values()),
                   "unit": "Exact HTTP JSON-body bytes; excludes headers, TCP/TLS and link-layer overhead",
                   "raw_training_rows_sent": 0},
              "elapsed_this_session_s": time.perf_counter() - started,
              "limitations": ["Synthetic fluid network; no RF, orbit or packet-level fidelity",
                  "Clients use separate processes/stores on the same host; not OS access isolation",
                  "Loopback HTTP bearer tokens; no TLS or secure aggregation in this local launcher",
                  "Model updates may leak information; no formal differential privacy guarantee",
                  "Allocator optimality applies to static fixed-route window only",
                  "FL prediction advantage and communication savings must be measured, not assumed"]}
    write_json(directory / "result.json", result)
    return result


def _counters(before, current):
    return {key: {field: before.get(key, {}).get(field, 0) + current.get(key, {}).get(field, 0)
                  for field in (before.get(key,{}).keys() | current.get(key,{}).keys())}
            for key in before.keys() | current.keys()}
