"""Real FL, explicit multihop paths, failure recovery and finite reservations."""

import unittest
from unittest.mock import patch
from tests import test_network_learning as fixtures
from backend.models.routing_event import RoutingEvent
from backend.models.network_learning import NetworkDataset, NetworkObservation
from backend.services.routing_event_service import reservations_for
from backend.services.link_telemetry_service import LINK_TARGET
from backend.services import routing_service


class ResearchTests(unittest.TestCase):
    setUp = fixtures.NetworkLearningTests.setUp
    tearDown = fixtures.NetworkLearningTests.tearDown

    def region(self):
        response = self.client.post("/api/research/region")
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def route(self, region, **kwargs):
        response = self.client.post(
            "/api/routing/event",
            json={
                "scenario_id": region["scenario_id"],
                "lat": 16.061,
                "lng": 108.22,
                "policy": "static",
                "topology": "adaptive",
                "load_ratio": 0,
                **kwargs,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def control(self, region, **kwargs):
        response = self.client.post(
            f"/api/research/{region['scenario_id']}/control", json=kwargs
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_explicit_access_and_backbone_paths_for_all_conditions(self):
        region = self.region()
        ids = region["nodes"]
        self.assertEqual(self.region()["scenario_id"], region["scenario_id"])
        normal = self.route(region, service="Message")
        self.assertEqual(
            normal["route"]["path"], [ids["ACCESS"], ids["RELAY"], ids["EDGE"]]
        )
        self.assertEqual(normal["destination"]["node_id"], ids["EDGE"])
        self.control(region, conditions="congested")
        crowded = self.route(region, service="Video Call")
        self.assertIn(ids["UAV"], crowded["route"]["path"])
        self.control(region, conditions="terrestrial_failure")
        alternate = self.route(region)
        self.assertIn(ids["UAV"], alternate["route"]["path"])
        self.control(region, conditions="satellite_fallback")
        satellite = self.route(region)
        self.assertEqual(
            satellite["route"]["path"],
            [ids["ACCESS"], ids["SHIP"], ids["SAT"], ids["EDGE"]],
        )
        self.assertGreater(satellite["route"]["distance_km"], 1000)
        self.assertLess(satellite["route"]["accessDistanceKm"], 1)
        self.assertFalse(satellite.get("mobility"))
        self.control(region, conditions="disconnected")
        self.assertEqual(self.route(region)["code"], "no_path")

    def test_link_training_target_future_labels_and_checkpoint_inference(self):
        region = self.region()
        request = {
            "scenario_id": region["scenario_id"],
            "task": "network_delay",
            "algorithm": "Predictive",
            "prediction_target": "application_link",
            "pool_mode": "all",
            "partition": "non_iid",
            "rounds": 2,
            "online_steps": 2,
            "samples_per_client": 40,
            "client_count": 6,
            "local_epochs": 1,
        }
        response = self.client.post("/api/fl/experiments", json=request)
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()["data"]["id"]
        detail = self.client.get(f"/api/fl/experiments/{identifier}").json()["data"]
        self.assertEqual(detail["status"], "COMPLETED", detail.get("error_message"))
        self.assertEqual(detail["config"]["target"], LINK_TARGET)
        self.assertEqual(
            detail["rounds"][0]["prediction_metrics"]["selection_source"],
            "uniform_clients_link_task",
        )
        with self.session() as db:
            dataset = db.get(NetworkDataset, detail["dataset_id"])
            self.assertEqual(dataset.config_json["label_unit"], "one_way_ms")
            rows = db.query(NetworkObservation).filter_by(dataset_id=dataset.id).all()
            self.assertTrue(
                all(
                    "source" in row.features_json and "target" in row.features_json
                    for row in rows
                )
            )
            self.assertTrue(
                all("target_delay_ms" not in row.features_json for row in rows)
            )
        with patch.object(
            routing_service, "predict", wraps=routing_service.predict
        ) as inference:
            result = self.route(region, policy="predictive", experiment_id=identifier)
        self.assertEqual(result["code"], "ok", result)
        inference.assert_called_once()
        self.assertTrue(
            all(
                "realized_next_tick_ms" not in row
                for row in inference.call_args.args[1]
            )
        )
        self.assertEqual(result["payload_bytes"], 4096)
        self.assertEqual(result["routing_decision"]["prediction_target"], LINK_TARGET)
        self.assertIn("realized_delay_change_ms", result["comparison"])
        self.assertEqual(result["delay_semantics"], "application_link_one_way_ms")

    def test_wait_retry_expiry_completion_and_bandwidth_release(self):
        region = self.region()
        body = {
            "scenario_id": region["scenario_id"],
            "lat": 16.061,
            "lng": 108.22,
            "policy": "static",
            "load_ratio": 0,
            "duration_s": 5,
            "wait_timeout_s": 10,
            "required_bandwidth_mbps": 6,
        }

        def save():
            response = self.client.post("/api/routing/events", json=body)
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()["data"]

        first = save()
        self.assertEqual(first["result"]["flow"]["state"], "transmitting")
        with self.session() as db:
            self.assertEqual(
                reservations_for(db, region["scenario_id"])["event_count"], 1
            )
        self.control(region, advance_s=5)
        saved = self.client.get(
            f"/api/routing/events?scenario_id={region['scenario_id']}"
        ).json()["data"][0]
        self.assertEqual(saved["result"]["flow"]["state"], "completed")
        with self.session() as db:
            self.assertEqual(
                reservations_for(db, region["scenario_id"])["event_count"], 0
            )
        self.control(region, conditions="disconnected")
        waiting = save()
        self.assertEqual(waiting["result"]["flow"]["state"], "waiting")
        self.control(region, advance_s=3, conditions="normal")
        with self.session() as db:
            self.assertEqual(
                db.get(RoutingEvent, waiting["id"]).result_json["flow"]["state"],
                "transmitting",
            )
        self.control(region, conditions="disconnected")
        self.control(region, advance_s=11)
        with self.session() as db:
            self.assertEqual(
                db.get(RoutingEvent, waiting["id"]).result_json["flow"]["state"],
                "expired",
            )
            self.assertEqual(
                reservations_for(db, region["scenario_id"])["event_count"], 0
            )


if __name__ == "__main__":
    unittest.main()
