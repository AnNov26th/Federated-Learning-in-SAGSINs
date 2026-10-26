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
        return {"runtime":"legacy", "task":"network_delay", "scenario_id":self.scenario_id, "algorithm":"Predictive",
                "rounds":3, "client_count":2, "local_epochs":2, "batch_size":16,
                "learning_rate":.03, "samples_per_client":40, "partition":"non_iid", "seed":19, **kwargs}

    def test_regional_preview_and_training_use_only_nearby_clients_including_ground(self):
        from backend.models.network_learning import NetworkDataset
        with self.session() as db:
            db.get(Node, "SEA").lng = 120
            db.commit()
        settings = self.payload(region_lat=0, region_lng=0, region_radius_km=130,
                                rounds=1, online_steps=1, local_epochs=1)
        context = self.client.get(f"/api/fl/training-context?scenario_id={self.scenario_id}&region_lat=0&region_lng=0&region_radius_km=130").json()["data"]
        self.assertEqual(set(context["candidate_pool"]), {"GROUND", "AIR"})
        preview = self.client.post("/api/fl/preview", json=settings)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["data"]["dataset_total"], 2 * 41)
        for _ in range(2):
            response = self.client.post("/api/fl/experiments", json=settings)
            self.assertEqual(response.status_code, 202, response.text)
            run = self.client.get(f"/api/fl/experiments/{response.json()['data']['id']}").json()["data"]
            self.assertEqual(run["status"], "COMPLETED", run["error_message"])
            self.assertEqual(set(run["config"]["candidate_pool"]), {"GROUND", "AIR"})
            self.assertEqual({row["client_id"] for row in run["rounds"][0]["clients"]}, {"GROUND", "AIR"})
            with self.session() as db:
                self.assertEqual(set(db.get(NetworkDataset, run["dataset_id"]).config_json["profiles"]), {"GROUND", "AIR"})
        rejected = self.client.post("/api/fl/experiments", json={**settings, "client_count": 3})
        self.assertEqual(rejected.status_code, 400)
        all_pool = self.client.get(f"/api/fl/training-context?scenario_id={self.scenario_id}&pool_mode=all").json()["data"]
        self.assertEqual(all_pool["candidate_count"], 4)

    def test_regional_selection_is_deterministic_respects_active_and_participant_pool(self):
        from backend.models.participant import Participant
        from backend.services.regional_pool_service import choose_region, ground_distance
        self.assertAlmostEqual(ground_distance(0, 179, 0, -179), 222.38985, places=3)
        with self.session() as db:
            nodes = db.query(Node).all()
            first, region = choose_region(nodes, radius_km=130)
            second, _ = choose_region(list(reversed(nodes)), radius_km=130)
            self.assertEqual([n.id for n in first], [n.id for n in second])
            self.assertIn("GROUND", [n.id for n in first])
            self.assertLessEqual(region["max_center_distance_km"], 130)
            db.get(Node, "SEA").status = "OFFLINE"
            db.add_all([Participant(node_id=name, selected=True, local_epochs=1, dataset_size=0)
                        for name in ("GROUND", "AIR", "SEA")])
            db.commit()
        result = self.client.get(f"/api/fl/training-context?scenario_id={self.scenario_id}").json()["data"]
        self.assertEqual(set(result["candidate_pool"]), {"GROUND", "AIR"})
        invalid = self.client.get(f"/api/fl/training-context?scenario_id={self.scenario_id}&region_lat=0")
        self.assertEqual(invalid.status_code, 422)

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

    def test_dynamic_profiles_reproduce_bursts_regimes_and_keep_target_alignment(self):
        from backend.services.network_dataset_service import temporal_channel_state
        self.assertEqual(temporal_channel_state("normal", 0, .3, 0), (.3, 1., 1., 0.))
        self.assertGreater(temporal_channel_state("bursty_congestion", 0, .3, 0)[1], 1)
        self.assertEqual(temporal_channel_state("bursty_congestion", 8, .3, 0)[1], 1)
        self.assertEqual(temporal_channel_state("regime_switching", 59, .3, 0)[1], 1)
        self.assertGreater(temporal_channel_state("regime_switching", 60, .3, 0)[1], 1)
        self.assertEqual(temporal_channel_state("regime_switching", 120, .3, 0)[1], 1)
        for profile in ("bursty_congestion", "regime_switching"):
            with self.session() as db:
                first = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40, network_profile=profile)
                second = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40, network_profile=profile)
                self.assertEqual(first.fingerprint, second.fingerprint)
                self.assertEqual(first.generator_version, "sagsin-network-v2-dynamic")
                rows = db.query(NetworkObservation).filter_by(dataset_id=first.id, client_id="GROUND").order_by(NetworkObservation.sequence).all()
                self.assertEqual(len(rows), 140)
                by_sequence = {row.sequence: row for row in rows}
                for row in rows:
                    following = by_sequence.get(row.sequence + 1)
                    if following:
                        self.assertAlmostEqual(row.target_delay_ms, following.features_json["observed_delay_ms"])
                self.assertGreater(max(row.features_json["packet_loss_ratio"] for row in rows), .035)
            response = self.client.post("/api/fl/experiments", json=self.payload(network_profile=profile, rounds=2))
            self.assertEqual(response.status_code, 202, response.text)
            detail = self.client.get(f"/api/fl/experiments/{response.json()['data']['id']}").json()["data"]
            self.assertEqual(detail["status"], "COMPLETED", detail["error_message"])

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
        expected_total_nodes = None
        with patch("backend.main.engine", self.engine):
            for _ in range(2):
                with TestClient(app) as client:
                    self.assertTrue(client.get("/api/health").json()["database_ready"])
                    self.assertIn("network_delay", client.get("/api/system").json()["learning_tasks"])
                    self.assertEqual(client.get("/api/test-db").json()["status"], "success")
                    self.assertEqual(client.get("/api/fl/datasets").status_code, 200)
                    self.assertIn("Federated network prediction", client.get("/fl.html").text)
                with self.session() as db:
                    self.assertEqual(db.query(Node).filter_by(scenario_id=self.scenario_id).count(), 4)
                    # Startup also bootstraps the separate global scenario.
                    # Preserve this fixture and ensure reload adds no duplicates.
                    total_nodes = db.query(Node).count()
                    if expected_total_nodes is None:
                        expected_total_nodes = total_nodes
                    self.assertEqual(total_nodes, expected_total_nodes)
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

    def test_preview_dynamic_limits_and_online_capacity(self):
        request = self.payload(samples_per_client=2500, online_steps=150, rounds=140, batch_size=1024,
                               local_epochs=25, learning_rate=.00001, timeout_ms=200000)
        response = self.client.post("/api/fl/preview", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["dataset_total"], 4 * 2650)
        self.assertEqual(data["pool_counts"]["train"], 4 * 1500)
        self.assertEqual(data["first_round_samples"], {"min":3000,"max":3000})
        self.assertEqual(data["parameters"], 961)
        bad = self.client.post("/api/fl/experiments", json=self.payload(rounds=101, online_steps=100))
        self.assertEqual(bad.status_code, 400)
        with self.session() as db:
            dataset = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40, online_steps=125)
            db.commit()
            dataset_id = dataset.id
        reused = self.client.post("/api/fl/preview", json=self.payload(dataset_id=dataset_id, rounds=120))
        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertEqual(reused.json()["data"]["per_client"]["online"]["min"],125)
        rejected = self.client.post("/api/fl/experiments", json=self.payload(dataset_id=dataset_id, rounds=126))
        self.assertEqual(rejected.status_code, 400, rejected.text)

    def test_more_than_fifty_clients_and_live_progress_survive_reconnect(self):
        with self.session() as db:
            db.add_all([Node(id=f"EXTRA-{i}", type="GROUND", lat=0, lng=0, alt=0, bandwidth=100,
                             latency=2, status="ACTIVE", scenario_id=self.scenario_id) for i in range(56)])
            db.commit()
        response = self.client.post("/api/fl/experiments", json=self.payload(client_count=60, rounds=1, online_steps=1, local_epochs=1))
        self.assertEqual(response.status_code,202,response.text)
        identifier = response.json()["data"]["id"]
        detail = self.client.get(f"/api/fl/experiments/{identifier}").json()["data"]
        self.assertEqual(detail["status"],"COMPLETED",detail["error_message"])
        self.assertEqual(detail["rounds"][0]["selected_count"],60)
        state = self.client.get(f"/api/fl/experiments/{identifier}/progress").json()["data"]
        self.assertEqual(state["progress"]["phase"],"completed")
        self.assertEqual(len(state["progress"]["clients"]),60)
        self.assertEqual(state["completed_rounds"],1)
        for _ in range(2):
            stream = self.client.get(f"/api/fl/experiments/{identifier}/events")
            self.assertEqual(stream.status_code,200)
            self.assertIn("event: progress",stream.text)
            self.assertIn('"status": "COMPLETED"',stream.text)

    def test_training_publishes_before_local_work_and_failure_is_durable(self):
        from backend.services import network_prediction_service as service
        original = service.train_local
        observed = []
        def trace(state, rows, config, seed):
            with self.session() as db:
                experiment = db.query(Experiment).order_by(Experiment.id.desc()).first()
                live = experiment.config_json["training_progress"]
                observed.append(live["clients"][rows[0].client_id]["status"])
            return original(state,rows,config,seed)
        with patch.object(service,"train_local",side_effect=trace):
            result = self.client.post("/api/fl/experiments",json=self.payload(rounds=1))
        self.assertEqual(result.status_code,202,result.text)
        self.assertEqual(observed,["TRAINING","TRAINING"])
        failed = self.client.post("/api/fl/experiments",json=self.payload(dropout_probability=1,rounds=1))
        identifier = failed.json()["data"]["id"]
        state = self.client.get(f"/api/fl/experiments/{identifier}/progress").json()["data"]
        self.assertEqual(state["status"],"FAILED")
        self.assertEqual(state["progress"]["phase"],"failed")

    def test_preview_reads_custom_splits_and_selected_pool_without_mutation(self):
        from backend.models.participant import Participant
        with self.session() as db:
            dataset = create_dataset(db, self.scenario_id, seed=19, samples_per_client=40)
            dataset_id=dataset.id
            db.query(NetworkObservation).filter(NetworkObservation.dataset_id==dataset_id,
                NetworkObservation.split=="train", NetworkObservation.sequence>=12).delete()
            db.add(Participant(node_id="GROUND",dataset_size=0,local_epochs=25,selected=True))
            db.add(Participant(node_id="AIR",dataset_size=0,local_epochs=30,selected=True))
            db.commit()
            count_before=db.query(NetworkObservation).count()
        response=self.client.post("/api/fl/preview",json=self.payload(dataset_id=dataset_id))
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()["data"]
        self.assertEqual(data["candidate_count"],2)
        self.assertEqual(data["dataset_client_count"],4)
        self.assertEqual(data["pool_counts"]["train"],24)
        self.assertEqual(data["per_client"]["train"],{"min":12,"max":12})
        self.assertEqual(data["dataset_total"],4*128)
        self.assertEqual(data["epoch_overrides"],2)
        with self.session() as db:
            self.assertEqual(db.query(NetworkObservation).count(),count_before)
            self.assertEqual(db.query(Experiment).count(),0)


if __name__ == "__main__":
    unittest.main()
