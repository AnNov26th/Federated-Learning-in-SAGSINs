"""Reproducible matched scheduler experiments with mean/std across seeds."""
import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", type=int, required=True)
    parser.add_argument("--demo", action="store_true", help="Use only data/network_demo/demo.sqlite")
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 42, 71])
    parser.add_argument("--profiles", nargs="+", choices=["normal", "high_latency", "low_bandwidth"], default=["normal"])
    parser.add_argument("--partitions", nargs="+", choices=["iid", "non_iid"], default=["non_iid"])
    parser.add_argument("--client-counts", type=int, nargs="+", default=[5])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--samples-per-client", type=int, default=160)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.demo:
        demo = root / "data" / "network_demo" / "demo.sqlite"
        if not demo.exists():
            parser.error("Run python -m backend.network_demo first.")
        os.environ["DATABASE_URL"] = "sqlite:///" + demo.as_posix()
    from fastapi import BackgroundTasks
    from backend.database.database import SessionLocal
    from backend.database.init_db import init_db
    from backend.models.simulation import Experiment
    from backend.routers.federated_learning import _detail, create_comparison
    from backend.schemas.fl import FLComparisonCreate
    from backend.services.fl_service import run_experiment
    init_db()
    outputs, rows = [], []
    for partition in args.partitions:
        for profile in args.profiles:
            for count in args.client_counts:
                for seed in args.seeds:
                    request = FLComparisonCreate(task="network_delay", scenario_id=args.scenario_id,
                        partition=partition, network_profile=profile, client_count=count, seed=seed,
                        rounds=args.rounds, samples_per_client=args.samples_per_client, local_epochs=2)
                    with SessionLocal() as db:
                        created = create_comparison(request, BackgroundTasks(), db).data
                    for summary in created["experiments"]:
                        run_experiment(summary["id"])
                        with SessionLocal() as db:
                            run = _detail(db, db.get(Experiment, summary["id"]))
                        outputs.append(run)
                        last = run["rounds"][-1] if run["rounds"] else {}
                        quality = last.get("prediction_metrics") or {}
                        row = {"experiment_id":run["id"], "comparison_id":created["comparison_id"],
                               "dataset_fingerprint":run["config"]["dataset_fingerprint"],
                               "seed":seed,"profile":profile,"partition":partition,"client_count":count,
                               "algorithm":run["algorithm"],"status":run["status"],
                               "mae_ms":quality.get("mae_ms"),"rmse_ms":quality.get("rmse_ms"),
                               "r2":quality.get("r2"),"persistence_mae_ms":quality.get("persistence_mae_ms"),
                               "total_communication_ms":sum(r["metrics"]["communication_time_ms"] for r in run["rounds"]),
                               "total_round_estimate_s":sum(r["round_duration_s"] for r in run["rounds"]),
                               "clients_completed":sum(r["participants_count"] for r in run["rounds"])}
                        rows.append(row)
                        print(json.dumps(row), flush=True)
    groups = defaultdict(list)
    for row in rows:
        if row["status"] == "COMPLETED":
            groups[(row["partition"],row["profile"],row["client_count"],row["algorithm"])].append(row)
    aggregates = []
    for key, group in groups.items():
        entry = dict(zip(("partition","profile","client_count","algorithm"),key))
        entry["seed_count"] = len(group)
        for metric in ("mae_ms","rmse_ms","total_communication_ms","total_round_estimate_s"):
            values = [row[metric] for row in group]
            entry[metric+"_mean"] = statistics.mean(values)
            entry[metric+"_std"] = statistics.stdev(values) if len(values) > 1 else 0.
        aggregates.append(entry)
    directory = root / "data" / "network_benchmarks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    (directory / "experiments.json").write_text(json.dumps(outputs,default=str,indent=2),encoding="utf-8")
    for name, values in (("runs",rows),("aggregates",aggregates)):
        if values:
            with (directory / f"{name}.csv").open("w",newline="",encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream,fieldnames=list(values[0]))
                writer.writeheader(); writer.writerows(values)
    print(f"Benchmark artifacts: {directory}")
    if any(row["status"] != "COMPLETED" for row in rows):
        raise SystemExit("Some experiments failed. Inspect runs.csv and experiments.json.")


if __name__ == "__main__":
    main()
