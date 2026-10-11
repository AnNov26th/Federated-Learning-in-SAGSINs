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
        with patch.object(MNISTDatasetManager, "load_data", load_tiny_dataset):
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
            self.assertEqual(db.query(Experiment).count(), 1)
            self.assertEqual(db.query(FLRound).count(), 1)
            self.assertEqual(db.query(FLClientRound).count(), 2)
            self.assertEqual(db.query(Metric).count(), 1)
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
