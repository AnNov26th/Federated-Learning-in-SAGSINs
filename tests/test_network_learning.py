"""Integration checks with generated data, real PyTorch training and isolated DB."""
import math
import unittest
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.database import Base, get_db
from backend.main import app
from backend.models.network import NetworkLink, Node
from backend.models.network_learning import NetworkObservation, NetworkRoundEvaluation
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound
from backend.services.network_dataset_service import create_dataset
from backend.services.scheduling_service import select_clients


class NetworkLearningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        with self.session() as db:
            scenario = Scenario(name="Four-layer test", total_nodes=4, ground=1, air=1, space=1, sea=1)
            db.add(scenario); db.flush()
            self.scenario_id = scenario.id
            for index, layer in enumerate(("GROUND", "AIR", "SPACE", "SEA")):
                db.add(Node(id=layer, type=layer, lat=0, lng=index, alt=index*10, bandwidth=100/(index+1),
                            latency=2+20*index, status="ACTIVE", scenario_id=scenario.id))
            db.flush()
            db.add(NetworkLink(source="GROUND", target="AIR", distance=25, bandwidth=10, latency=12, status="ACTIVE"))
            db.commit()
        def override_db():
            with self.session() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        self.worker_patch = patch("backend.services.fl_service.SessionLocal", self.session)
        self.worker_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.worker_patch.stop()
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    def payload(self, **kwargs):
        return {"task":"network_delay", "scenario_id":self.scenario_id, "algorithm":"Predictive",
                "rounds":3, "client_count":2, "local_epochs":2, "batch_size":16,
                "learning_rate":.03, "samples_per_client":40, "partition":"non_iid", "seed":19, **kwargs}

    def test_generator_repeatability_link_snapshot_and_temporal_boundaries(self):
        with self.session() as db:
            first = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40)
            second = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40)
            third = create_dataset(db, self.scenario_id, seed=20, samples_per_client=40)
            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertNotEqual(first.fingerprint, third.fingerprint)
            self.assertEqual(first.config_json["profiles"]["GROUND"]["bandwidth"],10)
            rows = db.query(NetworkObservation).filter_by(dataset_id=first.id, client_id="GROUND").all()
            second_rows = db.query(NetworkObservation).filter_by(dataset_id=second.id, client_id="GROUND").all()
            self.assertEqual([(r.features_json,r.target_delay_ms) for r in rows],[(r.features_json,r.target_delay_ms) for r in second_rows])
            splits = {name:[r.sequence for r in rows if r.split == name] for name in ("train","validation","online","test")}
            for earlier,later in zip(splits, list(splits)[1:]):
                self.assertLess(max(splits[earlier])+1,min(splits[later]))
            self.assertTrue(all("target_delay_ms" not in row.features_json for row in rows))

    def test_predictive_policy_uses_prediction_and_rejects_invalid_scores(self):
        profiles = {"A":{"status":"ACTIVE","latency":1,"bandwidth":100},"B":{"status":"ACTIVE","latency":100,"bandwidth":1}}
        self.assertEqual(select_clients("Predictive",list(profiles),profiles,1,1,2,.1,predicted_delays={"A":100,"B":2}),["B"])
        with self.assertRaises(ValueError):
            select_clients("Predictive",list(profiles),profiles,1,1,2,.1,predicted_delays={"A":float("nan"),"B":2})

    def test_main_startup_adds_missing_tables_and_preserves_data_on_reload(self):
        from sqlalchemy import inspect
        from backend.models.network_learning import NetworkDataset, NetworkRoundPrediction
        # Simulate an existing main database from before network learning.
        for model in (NetworkRoundPrediction, NetworkRoundEvaluation, NetworkObservation, NetworkDataset):
            model.__table__.drop(self.engine)
        with self.session() as db:
            existing = Experiment(scenario_id=self.scenario_id, algorithm="FedAvg", rounds=1,
                                  learning_rate=.01, status="COMPLETED", config_json={})
            db.add(existing); db.commit()
            existing_id = existing.id
        with patch("backend.main.engine", self.engine):
            for _ in range(2):
                with TestClient(app) as client:
                    self.assertTrue(client.get("/api/health").json()["database_ready"])
                    self.assertIn("network_delay", client.get("/api/system").json()["learning_tasks"])
                    self.assertEqual(client.get("/api/test-db").json()["status"], "success")
                    self.assertEqual(client.get("/api/fl/datasets").status_code, 200)
                    self.assertIn("Federated network prediction", client.get("/fl.html").text)
                with self.session() as db:
                    self.assertEqual(db.query(Node).count(), 4)
                    self.assertEqual(db.get(Experiment, existing_id).status, "COMPLETED")
                    self.assertEqual(db.query(NetworkDataset).count(), 0)
        self.assertIn("network_observations", inspect(self.engine).get_table_names())

    def test_end_to_end_training_audit_and_persisted_inference(self):
        response = self.client.post("/api/fl/experiments",json=self.payload())
        self.assertEqual(response.status_code,202,response.text)
        experiment_id = response.json()["data"]["id"]
        detail_response = self.client.get(f"/api/fl/experiments/{experiment_id}")
        self.assertEqual(detail_response.status_code,200,detail_response.text)
        detail = detail_response.json()["data"]
        self.assertEqual(detail["status"],"COMPLETED",detail["error_message"])
        self.assertIsNone(detail["latest_accuracy"])
        self.assertEqual(detail["completed_rounds"],3)
        for index, result in enumerate(detail["rounds"]):
            self.assertIsNone(result["accuracy"])
            self.assertTrue(math.isfinite(result["prediction_metrics"]["mae_ms"]))
            selected = [p for p in result["predictions"] if p["selected"]]
            self.assertEqual(len(selected),2)
            self.assertTrue(all(p["model_round"] == index for p in selected))
            self.assertEqual({p["client_id"] for p in selected},{c["client_id"] for c in result["clients"]})
            self.assertTrue(all(p["observed_delay_ms"] is None for p in result["predictions"] if not p["selected"]))
            if index:
                ranked = sorted(result["predictions"],key=lambda p:(p["predicted_delay_ms"],p["client_id"]))[:2]
                self.assertEqual({p["client_id"] for p in ranked},{p["client_id"] for p in selected})
        self.assertEqual(detail["rounds"][0]["prediction_metrics"]["selection_source"],"random_cold_start")
        raw = self.client.get(f"/api/fl/datasets/{detail['dataset_id']}/observations?split=test&limit=1").json()["data"]["rows"][0]
        result = self.client.post(f"/api/fl/experiments/{experiment_id}/predict",json=raw["features"])
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["data"]["model_round"],3)
        with self.session() as db:
            evaluation = db.query(NetworkRoundEvaluation).join(FLRound).filter(FLRound.experiment_id == experiment_id).first()
            self.assertTrue(any(abs(x) > 0 for row in evaluation.checkpoint_json["layers.4.weight"] for x in row))
        dataset = self.client.get(f"/api/fl/datasets/{detail['dataset_id']}").json()["data"]
        self.assertEqual(dataset["source"],"generated")

    def test_matched_comparison_shares_data_and_all_three_schedulers(self):
        payload = self.payload(rounds=2)
        payload.pop("algorithm")
        response = self.client.post("/api/fl/comparisons",json=payload)
        self.assertEqual(response.status_code,202,response.text)
        comparison = self.client.get(f"/api/fl/comparisons/{response.json()['data']['comparison_id']}")
        data = comparison.json()["data"]
        self.assertEqual(data["status"],"COMPLETED",data)
        self.assertEqual({run["algorithm"] for run in data["experiments"]},{"FedAvg","DelayAware","Predictive"})
        self.assertTrue(all(data[key] for key in ("same_dataset","same_seed","same_training_config","same_candidate_pool")))
        self.assertEqual(len({run["config"]["dataset_fingerprint"] for run in data["experiments"]}),1)

    def test_timeout_persists_attempted_round_without_aggregation(self):
        response = self.client.post("/api/fl/experiments",json=self.payload(timeout_ms=10))
        run = self.client.get(f"/api/fl/experiments/{response.json()['data']['id']}").json()["data"]
        self.assertEqual(run["status"],"FAILED")
        self.assertEqual(run["completed_rounds"],0)
        self.assertFalse(run["rounds"][0]["aggregated"])
        self.assertTrue(all(c["status"] == "TIMEOUT" and c["samples_used"] == 0 for c in run["rounds"][0]["clients"]))

    def test_centralized_control_and_task_validation(self):
        response = self.client.post("/api/fl/experiments",json=self.payload(algorithm="Centralized",rounds=1))
        run = self.client.get(f"/api/fl/experiments/{response.json()['data']['id']}").json()["data"]
        self.assertEqual(run["status"],"COMPLETED",run["error_message"])
        self.assertEqual(run["rounds"][0]["prediction_metrics"]["selection_source"],"centralized_control")
        invalid = self.client.post("/api/fl/experiments",json=self.payload(task="mnist"))
        self.assertEqual(invalid.status_code,422)

    def test_training_never_reads_validation_test_or_current_online_label(self):
        from backend.services import network_prediction_service as service
        original = service.train_local
        calls = []
        def trace(state, rows, config, seed):
            calls.append([(row.client_id,row.split,row.sequence) for row in rows])
            return original(state,rows,config,seed)
        with patch.object(service,"train_local",side_effect=trace):
            response = self.client.post("/api/fl/experiments",json=self.payload(rounds=2))
        self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(len(calls),4)
        self.assertTrue(all(len({row[0] for row in call}) == 1 for call in calls))
        self.assertTrue(all(row[1] not in {"validation","test"} for call in calls for row in call))
        self.assertTrue(all(row[1] == "train" for call in calls[:2] for row in call))
        with self.session() as db:
            online_start = db.query(NetworkObservation).filter_by(split="online").order_by(NetworkObservation.sequence).first().sequence
        self.assertTrue(all(row[2] == online_start for call in calls[2:] for row in call if row[1] == "online"))


if __name__ == "__main__":
    unittest.main()
