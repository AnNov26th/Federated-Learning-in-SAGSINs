"""Run a self-contained SAGSIN prediction demo in its own SQLite database.

python -m backend.network_demo --serve
"""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--rounds", type=int, default=5, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = root / "data" / "network_demo"
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + (directory / "demo.sqlite").as_posix()
    from fastapi import BackgroundTasks
    from backend.database.init_db import init_db
    from backend.database.database import SessionLocal
    from backend.database.seed_db import load_inventory
    from backend.models.network import Node
    from backend.models.scenario import Scenario
    from backend.routers.federated_learning import _detail, create_comparison
    from backend.schemas.fl import FLComparisonCreate
    from backend.services.fl_service import run_experiment

    init_db()
    with SessionLocal() as db:
        scenario = db.query(Scenario).filter_by(name="Network prediction demo 106").first()
        if scenario is None:
            inventory = load_inventory()
            scenario = Scenario(name="Network prediction demo 106", total_nodes=106, ground=50, sea=20, air=12, space=24)
            db.add(scenario); db.flush()
            for row in inventory:
                db.add(Node(id=row["id"], type=row["type"], lat=float(row["lat"]), lng=float(row["lng"]),
                            alt=float(row["alt_km"]), bandwidth=float(row["bandwidth_mbps"]), latency=float(row["latency_ms"]),
                            status="ACTIVE", scenario_id=scenario.id, is_simulated=True, platform=row["platform"] or None,
                            country_code=row["country_code"] or None, location_name=row["location_name"] or None))
            db.commit()
        response = create_comparison(FLComparisonCreate(
            scenario_id=scenario.id, task="network_delay", rounds=args.rounds, client_count=5,
            partition="non_iid", local_epochs=2, samples_per_client=80,
        ), BackgroundTasks(), db)
        identifiers = [item["id"] for item in response.data["experiments"]]
        comparison_id = response.data["comparison_id"]
    for experiment_id in identifiers:
        run_experiment(experiment_id)
    from backend.models.simulation import Experiment
    with SessionLocal() as db:
        details = [_detail(db, db.get(Experiment, identifier)) for identifier in identifiers]
    output = {"comparison_id": comparison_id, "experiments": details}
    (directory / "latest-comparison.json").write_text(json.dumps(output, default=str, indent=2), encoding="utf-8")
    for run in details:
        last = run["rounds"][-1] if run["rounds"] else {}
        print(json.dumps({"algorithm": run["algorithm"], "status": run["status"], "error": run["error_message"],
                          "prediction_metrics": last.get("prediction_metrics"),
                          "communication_ms": last.get("metrics", {}).get("communication_time_ms")}, ensure_ascii=False))
    if any(run["status"] != "COMPLETED" for run in details):
        raise SystemExit("Demo comparison failed; inspect latest-comparison.json.")
    print(f"Results: http://127.0.0.1:{args.port}/results.html?comparison_id={comparison_id}")
    if args.serve:
        import uvicorn
        uvicorn.run("backend.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
