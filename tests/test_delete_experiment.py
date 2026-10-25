"""Deletion must preserve unrelated experiments and shared training data."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.database.database import Base
from backend.delete_experiment import remove_experiment
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound
from backend.models.network import Node
from backend.services.network_dataset_service import create_dataset
from backend.models.network_learning import NetworkDataset, NetworkObservation


class DeleteExperimentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.temp = tempfile.TemporaryDirectory()
        with Session(self.engine) as db:
            scenario = Scenario(name="delete test", total_nodes=2, ground=2, air=0, space=0, sea=0)
            db.add(scenario); db.flush()
            for name in ("A", "B"):
                db.add(Node(id=name, scenario_id=scenario.id, type="GROUND", lat=0, lng=0,
                            alt=0, bandwidth=100, latency=2, status="ACTIVE"))
            db.flush()
            create_dataset(db, scenario.id, samples_per_client=40, online_steps=1)
            for identifier, status in ((1, "COMPLETED"), (2, "COMPLETED"), (3, "RUNNING")):
                db.add(Experiment(id=identifier, scenario_id=scenario.id, algorithm="FedAvg", rounds=1,
                                  learning_rate=.01, status=status, is_simulation=True, config_json={}))
                db.flush()
                db.add(FLRound(experiment_id=identifier, round=1, participants_count=2,
                               accuracy=0, loss=1, round_duration_s=1))
            db.commit()

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_exact_delete_has_verified_backup_and_preserves_shared_data(self):
        preview = remove_experiment(self.engine, 2, self.temp.name)
        self.assertEqual(preview["action"], "preview")
        with Session(self.engine) as db:
            count = db.query(NetworkObservation).count()
            self.assertEqual(db.query(Experiment).count(), 3)
        report = remove_experiment(self.engine, 2, self.temp.name, apply=True)
        with gzip.open(report["backup"], "rt", encoding="utf-8") as stream:
            backup = json.load(stream)
        self.assertEqual(backup["tables"]["experiments"][0]["id"], 2)
        self.assertEqual(len(backup["tables"]["fl_rounds"]), 1)
        with Session(self.engine) as db:
            self.assertEqual([r.id for r in db.query(Experiment).order_by(Experiment.id)], [1, 3])
            self.assertEqual(db.query(FLRound).count(), 2)
            self.assertEqual(db.query(NetworkDataset).count(), 1)
            self.assertEqual(db.query(NetworkObservation).count(), count)
            self.assertEqual(db.query(Node).count(), 2)

    def test_refuses_active_and_stale_latest_without_deleting(self):
        for identifier, latest in ((3, False), (2, True)):
            with self.assertRaises(ValueError):
                remove_experiment(self.engine, identifier, self.temp.name, apply=True, expect_latest=latest)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        with Session(self.engine) as db:
            self.assertEqual(db.query(Experiment).count(), 3)


if __name__ == "__main__":
    unittest.main()
