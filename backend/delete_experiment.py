"""Back up and remove exactly one terminal experiment; retain datasets/topology.

python -m backend.delete_experiment --id 4 --expect-latest --apply
"""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, delete, select


def remove_experiment(engine, identifier, backup_root, apply=False, expect_latest=False):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    names = ["network_round_predictions", "network_round_evaluations", "fl_client_rounds", "metrics", "fl_rounds", "experiments"]
    for table in metadata.tables.values():
        if table.name not in names and any(foreign.column.table.name in {"experiments", "fl_rounds"} for foreign in table.foreign_keys):
            raise ValueError(f"Unrecognized dependent table {table.name}; nothing was deleted.")
    experiments, rounds = metadata.tables["experiments"], metadata.tables["fl_rounds"]
    with engine.begin() as connection:
        row = connection.execute(select(experiments).where(experiments.c.id == identifier).with_for_update()).mappings().first()
        if row is None:
            raise ValueError("Experiment does not exist.")
        if row["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("Refusing to delete a queued/running experiment.")
        latest = connection.scalar(select(experiments.c.id).order_by(experiments.c.created_at.desc(), experiments.c.id.desc()).limit(1))
        if expect_latest and latest != identifier:
            raise ValueError(f"Latest experiment is now {latest}; requested {identifier}. Nothing deleted.")
        round_ids = select(rounds.c.id).where(rounds.c.experiment_id == identifier)
        clauses = {name: (metadata.tables[name].c.round_id.in_(round_ids)) for name in names[:4] if name in metadata.tables}
        clauses.update(fl_rounds=rounds.c.experiment_id == identifier, experiments=experiments.c.id == identifier)
        archived = {name: [dict(item) for item in connection.execute(select(metadata.tables[name]).where(clauses[name])).mappings()]
                    for name in names if name in metadata.tables}
        counts = {name: len(values) for name, values in archived.items()}
        if not apply:
            return {"action": "preview", "experiment_id": identifier, "counts": counts}
        directory = Path(backup_root) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-experiment-{identifier}")
        directory.mkdir(parents=True, exist_ok=False)
        backup = directory / "experiment.json.gz"
        with gzip.open(backup, "wt", encoding="utf-8") as stream:
            json.dump({"format":"sagsin-single-experiment-backup-v1", "experiment_id":identifier,
                       "counts":counts, "tables":archived}, stream, ensure_ascii=False, default=str)
        with gzip.open(backup, "rt", encoding="utf-8") as stream:
            check = json.load(stream)
        if check["counts"] != counts or check["tables"]["experiments"][0]["id"] != identifier:
            raise ValueError("Backup verification failed; nothing was deleted.")
        for name in names:
            if name in clauses:
                connection.execute(delete(metadata.tables[name]).where(clauses[name]))
    report = {"action":"deleted", "experiment_id":identifier, "counts":counts, "backup":str(backup),
              "preserved":"datasets, observations, nodes, links, participants and saved routing snapshots"}
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-latest", action="store_true")
    args = parser.parse_args()
    from backend.database.database import engine
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(remove_experiment(engine, args.id, root / "data/output/training_reset_backups", args.apply, args.expect_latest), ensure_ascii=True))


if __name__ == "__main__":
    main()
