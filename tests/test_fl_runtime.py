"""Small deterministic runtime checks for the FL API and training worker."""
import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"

import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from torch.utils.data import TensorDataset
from fastapi.testclient import TestClient

import backend.database.database as database
from backend.algorithms.fedavg import FedAvg
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric
from backend.utils.dataset_manager import MNISTDatasetManager


TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TEST_SESSION = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
database.engine = TEST_ENGINE
database.SessionLocal = TEST_SESSION

import backend.services.fl_service as fl_service
fl_service.SessionLocal = TEST_SESSION
from backend.main import app


class FedAvgRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.Base.metadata.create_all(bind=TEST_ENGINE)
        with TEST_SESSION() as db:
            scenario = Scenario(name="Test SAGSIN", total_nodes=2, ground=2)
            db.add(scenario)
            db.flush()
            db.add_all([
                Node(id="TEST-01", type="GROUND", lat=0, lng=0, alt=0, bandwidth=100, latency=2, battery_percent=100, status="ACTIVE", scenario_id=scenario.id),
                Node(id="TEST-02", type="GROUND", lat=0, lng=1, alt=0, bandwidth=100, latency=3, battery_percent=100, status="ACTIVE", scenario_id=scenario.id),
            ])
            db.commit()

    @classmethod
    def tearDownClass(cls):
        TEST_ENGINE.dispose()

    def test_weighted_aggregation(self):
        result = FedAvg.aggregate(
            [{"weight": torch.tensor([1.0, 3.0])}, {"weight": torch.tensor([7.0, 9.0])}],
            [1, 3],
        )
        self.assertTrue(torch.allclose(result["weight"], torch.tensor([5.5, 7.5])))

    def test_delay_aware_worker_uses_snapshot_and_persists_selected_client(self):
        def load_tiny_dataset(manager):
            generator = torch.Generator().manual_seed(61)
            manager.train_dataset = TensorDataset(
                torch.randn(64, 1, 28, 28, generator=generator),
                torch.arange(64) % 10,
            )
            manager.test_dataset = TensorDataset(
                torch.randn(32, 1, 28, 28, generator=generator),
                torch.arange(32) % 10,
            )
            return manager.train_dataset, manager.test_dataset

        def fast_local_train(global_state, dataset, config, seed):
            return global_state, len(dataset), 0.5, 0.6, 0.001

        with TEST_SESSION() as db:
            scenario = db.query(Scenario).first()
            db.add_all([
                Node(id="DELAY-SLOW", type="GROUND", lat=0, lng=0, alt=0, bandwidth=0.1, latency=100, battery_percent=100, status="ACTIVE", scenario_id=scenario.id),
                Node(id="DELAY-FAST", type="GROUND", lat=0, lng=1, alt=0, bandwidth=100, latency=2, battery_percent=100, status="ACTIVE", scenario_id=scenario.id),
                Node(id="DELAY-OFFLINE", type="GROUND", lat=0, lng=2, alt=0, bandwidth=1000, latency=0, battery_percent=100, status="OFFLINE", scenario_id=scenario.id),
            ])
            db.flush()
            experiment = Experiment(
                scenario_id=scenario.id,
                algorithm="DelayAware",
                rounds=1,
                learning_rate=0.01,
                status="QUEUED",
                config_json={
                    "seed": 61, "partition": "iid", "client_count": 1,
                    "candidate_pool": ["DELAY-SLOW", "DELAY-FAST", "DELAY-OFFLINE"],
                    "client_profiles": {
                        "DELAY-SLOW": {"status": "ACTIVE", "latency": 100, "bandwidth": 0.1},
                        "DELAY-FAST": {"status": "ACTIVE", "latency": 2, "bandwidth": 100},
                        "DELAY-OFFLINE": {"status": "OFFLINE", "latency": 0, "bandwidth": 1000},
                    },
                    "local_epochs": 1, "batch_size": 16, "network_profile": "normal",
                    "dropout_probability": 0, "timeout_ms": 30000,
                },
            )
            db.add(experiment)
            db.commit()
            experiment_id = experiment.id

        with patch.object(MNISTDatasetManager, "load_data", load_tiny_dataset), \
             patch.object(fl_service, "_train_local", fast_local_train):
            fl_service.run_experiment(experiment_id)

        with TEST_SESSION() as db:
            experiment = db.query(Experiment).filter_by(id=experiment_id).one()
            round_row = db.query(FLRound).filter_by(experiment_id=experiment_id).one()
            outcomes = db.query(FLClientRound).filter_by(round_id=round_row.id).all()
            self.assertEqual(experiment.status, "COMPLETED", experiment.error_message)
            self.assertEqual(round_row.participants_count, 1)
            self.assertEqual([outcome.client_id for outcome in outcomes], ["DELAY-FAST"])

    def test_all_client_dropout_persists_attempted_round_before_failure(self):
        def load_tiny_dataset(manager):
            generator = torch.Generator().manual_seed(67)
            manager.train_dataset = TensorDataset(
                torch.randn(32, 1, 28, 28, generator=generator),
                torch.arange(32) % 10,
            )
            manager.test_dataset = TensorDataset(
                torch.randn(16, 1, 28, 28, generator=generator),
                torch.arange(16) % 10,
            )
            return manager.train_dataset, manager.test_dataset

        with TEST_SESSION() as db:
            scenario = db.query(Scenario).first()
            experiment = Experiment(
                scenario_id=scenario.id,
                algorithm="DelayAware",
                rounds=1,
                learning_rate=0.01,
                status="QUEUED",
                config_json={
                    "seed": 67, "partition": "iid", "client_count": 2,
                    "candidate_pool": ["TEST-01", "TEST-02"],
                    "client_profiles": {
                        "TEST-01": {"status": "ACTIVE", "latency": 2, "bandwidth": 100},
                        "TEST-02": {"status": "ACTIVE", "latency": 3, "bandwidth": 100},
                    },
                    "local_epochs": 1, "batch_size": 16, "network_profile": "normal",
                    "dropout_probability": 1, "timeout_ms": 30000,
                },
            )
            db.add(experiment)
            db.commit()
            experiment_id = experiment.id

        def fast_local_train(global_state, dataset, config, seed):
            return global_state, len(dataset), 0.5, 0.6, 0.001

        with patch.object(MNISTDatasetManager, "load_data", load_tiny_dataset), \
             patch.object(fl_service, "_train_local", fast_local_train):
            fl_service.run_experiment(experiment_id)

        with TEST_SESSION() as db:
            experiment = db.query(Experiment).filter_by(id=experiment_id).one()
            round_row = db.query(FLRound).filter_by(experiment_id=experiment_id).one()
            outcomes = db.query(FLClientRound).filter_by(round_id=round_row.id).all()
            self.assertEqual(experiment.status, "FAILED")
            self.assertIn("no clients completed", experiment.error_message.lower())
            self.assertEqual(round_row.participants_count, 0)
            self.assertEqual({outcome.status for outcome in outcomes}, {"DROPPED"})

    def test_comparison_api_queues_matched_runs_and_returns_audit_data(self):
        payload = {
            "rounds": 2, "client_count": 2, "local_epochs": 1,
            "batch_size": 16, "learning_rate": 0.01, "partition": "iid",
            "seed": 71, "network_profile": "normal", "dropout_probability": 0,
            "timeout_ms": 30000,
        }
        with patch("backend.routers.federated_learning.run_experiment"):
            client = TestClient(app)
            created = client.post("/api/fl/comparisons", json=payload)
            self.assertEqual(created.status_code, 202, created.text)
            summary = created.json()["data"]
            with TEST_SESSION() as db:
                first_id = summary["experiments"][0]["id"]
                round_row = FLRound(
                    experiment_id=first_id, round=1, participants_count=1,
                    accuracy=0.5, loss=0.6, round_duration_s=0.2,
                )
                db.add(round_row)
                db.flush()
                db.add(FLClientRound(
                    round_id=round_row.id, client_id="TEST-01", status="COMPLETED",
                    samples_used=32, training_duration_s=0.1, latency_ms=2,
                    communication_time_ms=10, data_transferred_mb=0.1,
                ))
                db.add(Metric(
                    round_id=round_row.id, latency_ms=2, communication_time_ms=10,
                    energy_j=2, bandwidth_mbps=100, data_transferred_mb=0.1,
                    packet_loss_ratio=0,
                ))
                db.query(Experiment).filter_by(id=summary["experiments"][0]["id"]).one().status = "FAILED"
                db.commit()
            comparison = client.get(f"/api/fl/comparisons/{summary['comparison_id']}")
        self.assertEqual(comparison.status_code, 200, comparison.text)
        data = comparison.json()["data"]
        self.assertEqual(data["status"], "RUNNING")
        self.assertEqual(len(data["experiments"]), 2)
        self.assertTrue(data["same_candidate_pool"])
        self.assertTrue(data["same_seed"])
        self.assertTrue(data["same_training_config"])
        configs = [run["config"] for run in data["experiments"]]
        self.assertEqual({run["selection_policy"] for run in configs}, {"round_sample"})
        self.assertEqual({run["seed"] for run in configs}, {71})
        self.assertEqual({run["algorithm"] for run in data["experiments"]}, {"FedAvg", "DelayAware"})
        self.assertEqual(data["experiments"][0]["rounds"][0]["clients"][0]["client_id"], "TEST-01")
        self.assertEqual(data["experiments"][0]["rounds"][0]["metrics"]["client_failure_ratio"], 0.0)
        with TEST_SESSION() as db:
            db.query(Experiment).filter_by(id=summary["experiments"][1]["id"]).one().status = "FAILED"
            db.commit()
        self.assertEqual(client.get(f"/api/fl/comparisons/{summary['comparison_id']}").json()["data"]["status"], "FAILED")

    def test_experiment_rejects_scenario_without_enough_active_nodes(self):
        with TEST_SESSION() as db:
            scenario = Scenario(name="No active nodes", total_nodes=0, ground=0)
            db.add(scenario)
            db.commit()
            scenario_id = scenario.id
        client = TestClient(app)
        response = client.post("/api/fl/experiments", json={
            "scenario_id": scenario_id, "algorithm": "FedAvg", "rounds": 1,
            "client_count": 2, "local_epochs": 1, "learning_rate": 0.01,
            "batch_size": 16, "partition": "iid", "seed": 5,
            "network_profile": "normal", "dropout_probability": 0,
            "timeout_ms": 30000,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("client hợp lệ", response.json()["detail"])

    def test_api_worker_trains_and_persists_round_and_clients(self):
        def load_tiny_dataset(manager):
            generator = torch.Generator().manual_seed(17)
            manager.train_dataset = TensorDataset(
                torch.randn(64, 1, 28, 28, generator=generator),
                torch.arange(64) % 10,
            )
            manager.test_dataset = TensorDataset(
                torch.randn(32, 1, 28, 28, generator=generator),
                torch.arange(32) % 10,
            )
            return manager.train_dataset, manager.test_dataset

        payload = {
            "rounds": 1,
            "client_count": 2,
            "local_epochs": 1,
            "batch_size": 16,
            "learning_rate": 0.01,
            "partition": "iid",
            "seed": 9,
            "network_profile": "normal",
            "dropout_probability": 0,
            "timeout_ms": 30000,
        }
        with TEST_SESSION() as db:
            previous_experiments = db.query(Experiment).count()
        def fast_local_train(global_state, dataset, config, seed):
            return global_state, len(dataset), 0.5, 0.6, 0.001

        with patch.object(MNISTDatasetManager, "load_data", load_tiny_dataset), \
             patch.object(fl_service, "_train_local", fast_local_train):
            client = TestClient(app)
            response = client.post("/api/fl/experiments", json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            experiment_id = response.json()["data"]["id"]
            result = client.get(f"/api/fl/experiments/{experiment_id}")

        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()["data"]
        self.assertEqual(data["status"], "COMPLETED", data.get("error_message"))
        self.assertEqual(data["completed_rounds"], 1)
        self.assertGreaterEqual(data["rounds"][0]["accuracy"], 0)
        self.assertEqual(data["rounds"][0]["selected_count"], 2)
        self.assertEqual(data["rounds"][0]["participants_count"], 2)
        self.assertEqual(sum(c["samples_used"] for c in data["rounds"][0]["clients"]), 64)
        with TEST_SESSION() as db:
            self.assertEqual(db.query(Experiment).filter_by(id=experiment_id).count(), 1)
            rounds = db.query(FLRound).filter_by(experiment_id=experiment_id).all()
            self.assertEqual(len(rounds), 1)
            self.assertEqual(db.query(FLClientRound).filter_by(round_id=rounds[0].id).count(), 2)
            self.assertEqual(db.query(Metric).filter_by(round_id=rounds[0].id).count(), 1)
            self.assertEqual(db.query(Experiment).count(), previous_experiments + 1)
            self.assertEqual(db.query(Participant).count(), 2)

    def test_round_timeout_is_counted_in_duration_and_energy(self):
        def load_tiny_dataset(manager):
            generator = torch.Generator().manual_seed(23)
            manager.train_dataset = TensorDataset(
                torch.randn(64, 1, 28, 28, generator=generator),
                torch.arange(64) % 10,
            )
            manager.test_dataset = TensorDataset(
                torch.randn(32, 1, 28, 28, generator=generator),
                torch.arange(32) % 10,
            )
            return manager.train_dataset, manager.test_dataset

        def fast_local_train(global_state, dataset, config, seed):
            return global_state, len(dataset), 0.5, 0.6, 0.001

        with TEST_SESSION() as db:
            nodes = {node.id: node for node in db.query(Node).all()}
            for node in nodes.values():
                if node.id not in {"TEST-01", "TEST-02"}:
                    node.status = "OFFLINE"
            nodes["TEST-01"].bandwidth = 1_000_000
            nodes["TEST-02"].bandwidth = 1
            db.commit()

        payload = {
            "rounds": 1,
            "client_count": 2,
            "local_epochs": 1,
            "batch_size": 16,
            "learning_rate": 0.01,
            "partition": "iid",
            "seed": 31,
            "network_profile": "high_latency",
            "dropout_probability": 0,
            "timeout_ms": 50,
        }
        with patch.object(MNISTDatasetManager, "load_data", load_tiny_dataset), \
             patch.object(fl_service, "_train_local", fast_local_train):
            client = TestClient(app)
            response = client.post("/api/fl/experiments", json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            experiment_id = response.json()["data"]["id"]
            result = client.get(f"/api/fl/experiments/{experiment_id}")

        self.assertEqual(result.status_code, 200, result.text)
        round_result = result.json()["data"]["rounds"][0]
        outcomes = {row["status"]: row for row in round_result["clients"]}
        self.assertIn("COMPLETED", outcomes)
        self.assertIn("TIMEOUT", outcomes)
        self.assertEqual(outcomes["TIMEOUT"]["communication_time_ms"], 50)
        self.assertGreaterEqual(round_result["round_duration_s"], 0.05)
        with TEST_SESSION() as db:
            metric = db.query(Metric).order_by(Metric.id.desc()).first()
            self.assertGreaterEqual(metric.energy_j, 0.5)
            self.assertAlmostEqual(metric.communication_time_ms, 50, delta=1)


if __name__ == "__main__":
    unittest.main()
