"""Paired data-volume experiment on a new, isolated SQLite database.

python -m backend.network_volume_demo --seeds 11 42 71 --rounds 10

Generate 2,000 historical observations/client. Compare 1,200 local train
samples with its most recent 192-sample subset (the training allocation of
320 historical samples). Both runs retain IDENTICAL 400 validation, 100
online and 400 test samples/client. The small dataset therefore has 992
historical samples, not a conventional 320-sample 60/20/20 split.
"""
import argparse
import csv
import hashlib
import json
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, default=str, indent=2), encoding="utf-8")


def csv_file(path, rows):
    if rows:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def benchmark_inputs(output_directory):
    """Match the input tree to a benchmark run; retain legacy custom folders."""
    out = Path(output_directory)
    if out.parent.name == "network_benchmarks" and out.parent.parent.name == "output":
        return out.parents[2] / "input" / "network_benchmarks" / out.name
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 42, 71])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--clients", type=int, default=24)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "output" / "network_benchmarks" / ("volume_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(parents=True, exist_ok=False)
    inputs = benchmark_inputs(out)
    inputs.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + (out / "demo.sqlite").as_posix()
    print(f"ARTIFACT_DIRECTORY={out}", flush=True)
    from sqlalchemy import insert, literal, select
    from fastapi import BackgroundTasks
    from backend.database.database import SessionLocal
    from backend.database.init_db import init_db
    from backend.database.migrations import SCENARIO_NAME
    from backend.models.network import Node, NetworkLink
    from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation
    from backend.models.scenario import Scenario
    from backend.models.simulation import Experiment, FLRound
    from backend.routers.federated_learning import create_experiment, _detail
    from backend.schemas.fl import FLExperimentCreate
    from backend.services.fl_service import run_experiment
    from backend.services.network_dataset_service import create_dataset, dataset_summary
    from backend.algorithms.network_delay_model import NetworkDelayRegressor, payload_bytes

    init_db()
    with SessionLocal() as db:
        scenario = db.query(Scenario).filter_by(name=SCENARIO_NAME).one()
        scenario_id = scenario.id
        nodes = db.query(Node).filter_by(scenario_id=scenario_id).order_by(Node.id).all()
        csv_file(inputs / "nodes.csv", [{key: getattr(node, key) for key in ("id", "type", "lat", "lng", "alt", "bandwidth", "latency", "status")} for node in nodes])
        links = db.query(NetworkLink).order_by(NetworkLink.id).all()
        csv_file(inputs / "links.csv", [{key: getattr(link, key) for key in ("id", "source", "target", "distance", "bandwidth", "latency", "status")} for link in links])
    manifest = {
        "scenario_id": scenario_id, "candidate_clients": len(nodes), "clients_per_round": args.clients,
        "seeds": args.seeds, "rounds": args.rounds, "profiles": ["normal", "bursty_congestion", "regime_switching"],
        "architecture": "12 -> 32 -> 16 -> 1", "parameters": sum(p.numel() for p in NetworkDelayRegressor().parameters()),
        "payload_bytes": payload_bytes(), "local_epochs": 2, "learning_rate": .01, "batch_size": 64,
        "partition": "non_iid", "dropout_probability": 0, "timeout_ms": 120000,
        "design": "Paired recent train subset 192 versus 1200 samples/client; identical validation/online/test and initialization seed.",
        "historical_source_samples_per_client": 2000,
        "small_dataset_note": "192 train + 400 validation + 400 test = 992 historical; 100 online extra. 192 is the train allocation of a conventional 320-history run, but this is NOT that conventional split.",
        "limitations": ["Synthetic single-topology demo, not measured network traffic.",
                        "Equal epochs means more optimizer steps in the larger-data run; compute budget is not equal.",
                        "Predictive selection changes local histories; comparisons include that feedback.",
                        "Three temporal profiles, not a cross-profile train-to-test generalization study.",
                        "The final round is preselected; test scores are not used to choose checkpoints."],
    }
    dump(inputs / "manifest.json", manifest)
    summary_rows, round_rows = [], []
    for profile in manifest["profiles"]:
        for seed in args.seeds:
            pair_dir = out / f"{profile}_seed{seed}"
            pair_dir.mkdir()
            pair_inputs = inputs / pair_dir.name
            pair_inputs.mkdir()
            print(f"GENERATING profile={profile} seed={seed} historical=2000", flush=True)
            with SessionLocal() as db:
                large = create_dataset(db, scenario_id, seed, 2000, "non_iid", profile)
                db.commit()
                large_id = large.id
                config = dict(large.config_json)
                config.update(samples_per_client=992, train_samples_per_client=192,
                              source_dataset_id=large_id, subset_rule="train sequence >= 1008; all other splits unchanged",
                              split_design="paired_fixed_holdout", source_historical_samples_per_client=2000)
                fingerprint = hashlib.sha256(json.dumps({"source": large.fingerprint, "config": config}, sort_keys=True).encode()).hexdigest()
                small = NetworkDataset(scenario_id=scenario_id, seed=seed, generator_version=large.generator_version + "-subset",
                                       fingerprint=fingerprint, config_json=config)
                db.add(small)
                db.flush()
                small_id = small.id
                table = NetworkObservation.__table__
                columns = ["dataset_id", "client_id", "sequence", "split", "features_json", "target_delay_ms"]
                db.execute(insert(table).from_select(columns, select(literal(small_id), table.c.client_id, table.c.sequence,
                    table.c.split, table.c.features_json, table.c.target_delay_ms).where(
                        table.c.dataset_id == large_id, (table.c.split != "train") | (table.c.sequence >= 1008))))
                db.commit()
                for name, dataset in (("small", small), ("large", large)):
                    dump(pair_inputs / f"{name}_dataset_metadata.json", {**dataset_summary(db, dataset), "config": dataset.config_json})
                # Full source CSV also reconstructs the small set with its explicit subset rule.
                with (pair_inputs / "source_observations.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = None
                    for row in db.execute(select(table).where(table.c.dataset_id == large_id).order_by(table.c.client_id, table.c.sequence)).mappings().yield_per(2000):
                        flat = {key: row[key] for key in ("id", "dataset_id", "client_id", "sequence", "split")}
                        flat.update(row["features_json"])
                        flat["target_delay_ms"] = row["target_delay_ms"]
                        if writer is None:
                            writer = csv.DictWriter(stream, fieldnames=list(flat))
                            writer.writeheader()
                        writer.writerow(flat)
            for condition, dataset_id, historical, train_count in (("small", small_id, 992, 192), ("large", large_id, 2000, 1200)):
                request = FLExperimentCreate(pool_mode="all", task="network_delay", algorithm="Predictive", scenario_id=scenario_id,
                    dataset_id=dataset_id, samples_per_client=historical, rounds=args.rounds, client_count=args.clients,
                    local_epochs=2, learning_rate=.01, batch_size=64, partition="non_iid", seed=seed,
                    network_profile=profile, dropout_probability=0, timeout_ms=120000)
                dump(pair_inputs / f"{condition}_request.json", request.model_dump())
                with SessionLocal() as db:
                    created = create_experiment(request, BackgroundTasks(), db).data
                    experiment_id = created["id"]
                print(f"TRAINING profile={profile} seed={seed} condition={condition} experiment={experiment_id}", flush=True)
                started = time.perf_counter()
                run_experiment(experiment_id)
                elapsed = time.perf_counter() - started
                with SessionLocal() as db:
                    detail = _detail(db, db.get(Experiment, experiment_id))
                    dump(pair_dir / f"{condition}_experiment.json", detail)
                    audits, clients = [], []
                    for result in detail["rounds"]:
                        for item in result["predictions"]:
                            audits.append(dict(round=result["round"], **item))
                        for item in result["clients"]:
                            clients.append(dict(round=result["round"], **item))
                        round_rows.append(dict(profile=profile, seed=seed, condition=condition, experiment_id=experiment_id,
                            round=result["round"], **(result["prediction_metrics"] or {})))
                    csv_file(pair_dir / f"{condition}_decision_audit.csv", audits)
                    csv_file(pair_dir / f"{condition}_client_outcomes.csv", clients)
                    final_round = db.query(FLRound).filter_by(experiment_id=experiment_id).order_by(FLRound.round.desc()).first()
                    evaluation = db.get(NetworkRoundEvaluation, final_round.id) if final_round else None
                    if evaluation:
                        dump(pair_dir / f"{condition}_checkpoint.json", dict(experiment_id=experiment_id, dataset_id=dataset_id,
                             round=final_round.round, architecture=manifest["architecture"], state_dict=evaluation.checkpoint_json))
                if detail["status"] != "COMPLETED":
                    raise RuntimeError(f"Experiment {experiment_id} failed: {detail['error_message']}")
                last = detail["rounds"][-1]["prediction_metrics"]
                summary = dict(profile=profile, seed=seed, condition=condition, experiment_id=experiment_id,
                    dataset_id=dataset_id, candidate_clients=len(nodes), train_samples_per_client=train_count,
                    initial_train_samples=len(nodes)*train_count, first_round_selected_samples=args.clients*train_count,
                    mae_ms=last["mae_ms"], rmse_ms=last["rmse_ms"], persistence_mae_ms=last["persistence_mae_ms"],
                    improvement_over_persistence_percent=100*(last["persistence_mae_ms"]-last["mae_ms"])/last["persistence_mae_ms"],
                    test_samples=last["test_samples"], host_wall_seconds=elapsed,
                    samples_used=sum(item["samples_used"] for item in clients),
                    total_communication_ms=sum(result["metrics"]["communication_time_ms"] for result in detail["rounds"]))
                summary_rows.append(summary)
                csv_file(out / "runs.csv", summary_rows)
                csv_file(out / "round_metrics.csv", round_rows)
                print(json.dumps(summary), flush=True)
    paired = []
    for profile in manifest["profiles"]:
        for seed in args.seeds:
            small = next(row for row in summary_rows if row["profile"] == profile and row["seed"] == seed and row["condition"] == "small")
            large = next(row for row in summary_rows if row["profile"] == profile and row["seed"] == seed and row["condition"] == "large")
            assert small["persistence_mae_ms"] == large["persistence_mae_ms"]
            paired.append(dict(profile=profile, seed=seed, small_mae_ms=small["mae_ms"], large_mae_ms=large["mae_ms"],
                               mae_reduction_ms=small["mae_ms"]-large["mae_ms"],
                               mae_reduction_percent=100*(small["mae_ms"]-large["mae_ms"])/small["mae_ms"]))
    csv_file(out / "paired_differences.csv", paired)
    groups = defaultdict(list)
    for row in summary_rows:
        groups[row["profile"], row["condition"]].append(row)
    aggregates = []
    for (profile, condition), group in groups.items():
        aggregate = dict(profile=profile, condition=condition, seed_count=len(group))
        for metric in ("mae_ms", "rmse_ms", "persistence_mae_ms", "host_wall_seconds", "improvement_over_persistence_percent"):
            values = [row[metric] for row in group]
            aggregate[metric+"_mean"] = statistics.mean(values)
            aggregate[metric+"_std"] = statistics.stdev(values) if len(values)>1 else 0.
        aggregates.append(aggregate)
    csv_file(out / "aggregates.csv", aggregates)
    print(f"COMPLETED artifacts={out}", flush=True)


if __name__ == "__main__":
    main()
