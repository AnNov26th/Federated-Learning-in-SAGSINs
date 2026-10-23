"""Inspect or reset training records; preserve topology and back up before deletion.

python -m backend.reset_training --database main --apply
python -m backend.reset_training --database demo --apply
"""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, create_engine, delete, func, inspect, select, update

TRAINING_TABLES = (
    "network_round_predictions", "network_round_evaluations", "fl_client_rounds",
    "metrics", "fl_rounds", "experiments", "network_observations", "network_datasets",
)
PRESERVED_TABLES = ("scenarios", "nodes", "network_links", "participants")


def reset_training(engine, backup_directory, apply=False):
    metadata = MetaData()
    available = set(inspect(engine).get_table_names())
    names = [name for name in (*TRAINING_TABLES, *PRESERVED_TABLES) if name in available]
    metadata.reflect(bind=engine, only=names)
    with engine.begin() as connection:
        counts = {name: connection.scalar(select(func.count()).select_from(metadata.tables[name])) for name in names}
        if not apply:
            return {"action": "inspect", "counts": counts}
        experiments = metadata.tables.get("experiments")
        if experiments is not None:
            active = connection.scalar(select(func.count()).select_from(experiments).where(
                experiments.c.status.in_(["RUNNING", "QUEUED"])))
            if active:
                raise RuntimeError("Stop or finish active training jobs before resetting.")
        backup_directory.mkdir(parents=True, exist_ok=False)
        backup_file = backup_directory / "training.jsonl.gz"
        # Stream rows to avoid loading the entire telemetry dataset into RAM.
        with gzip.open(backup_file, "wt", encoding="utf-8") as archive:
            archive.write(json.dumps({"format": "sagsin-training-backup-v1", "counts": counts}) + "\n")
            for name in (*TRAINING_TABLES, "participants"):
                if name not in available:
                    continue
                for row in connection.execute(select(metadata.tables[name])).mappings():
                    archive.write(json.dumps({"table": name, "row": dict(row)}, default=str, ensure_ascii=False) + "\n")
        # Child tables first; preserve foreign-key enforcement and transactionality.
        for name in TRAINING_TABLES:
            if name in available:
                connection.execute(delete(metadata.tables[name]))
        if "participants" in available:
            connection.execute(update(metadata.tables["participants"]).values(dataset_size=0, selected=False))
        after = {name: connection.scalar(select(func.count()).select_from(metadata.tables[name])) for name in names}
        if any(after.get(name, 0) for name in TRAINING_TABLES):
            raise RuntimeError("Reset verification failed; transaction rolled back.")
        if any(after.get(name) != counts.get(name) for name in PRESERVED_TABLES if name in counts):
            raise RuntimeError("Topology count changed; transaction rolled back.")
    report = {"action": "reset", "before": counts, "after": after, "backup": str(backup_file)}
    (backup_directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", choices=("main", "demo"), default="main")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.database == "main":
        from backend.database.database import engine
    else:
        database_file = root / "data/network_demo/demo.sqlite"
        if not database_file.is_file():
            raise SystemExit("Demo database does not exist.")
        engine = create_engine("sqlite:///" + database_file.as_posix())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = reset_training(engine, root / "data/training_reset_backups" / (timestamp + "-" + args.database), args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
