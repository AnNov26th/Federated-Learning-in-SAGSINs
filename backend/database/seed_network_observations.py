"""Append generated network observations without deleting any existing records."""
import argparse
import json

from backend.database.database import SessionLocal
from backend.database.init_db import init_db
from backend.models.scenario import Scenario
from backend.services.network_dataset_service import create_dataset, dataset_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True, type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples-per-client", type=int, default=160)
    parser.add_argument("--online-steps", type=int, default=100)
    parser.add_argument("--partition", choices=("iid", "non_iid"), default="non_iid")
    parser.add_argument("--network-profile", choices=("normal", "high_latency", "low_bandwidth", "bursty_congestion", "regime_switching"), default="normal")
    args = parser.parse_args()
    if not 0 <= args.seed <= 2147483647:
        parser.error("seed must be between 0 and 2147483647")
    init_db()
    with SessionLocal() as db:
        if db.get(Scenario, args.scenario_id) is None:
            parser.error("Scenario not found. Create a topology first.")
        try:
            dataset = create_dataset(db, **vars(args))
            db.commit()
            print(json.dumps(dataset_summary(db, dataset), default=str, indent=2))
        except ValueError as exc:
            parser.error(str(exc))


if __name__ == "__main__":
    main()
