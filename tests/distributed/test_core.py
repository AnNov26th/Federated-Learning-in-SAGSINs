import copy
import math
from pathlib import Path
import tempfile
import unittest
import torch
from fastapi.testclient import TestClient
from sagsin.allocation import allocate, assert_capacity
from sagsin.client import create_client
from sagsin.config import ExperimentConfig
from sagsin.dataset import feature_row, generate
from sagsin.fedavg import FedAvg
from sagsin.model import DelayModel, envelope, predictions, validate_envelope
from sagsin.routing import edge_costs, shortest_path
from sagsin.simulation import simulate, workload
from sagsin.storage import read_json, write_json
from sagsin.topology import LINKS, channel, public_topology


class AllocationTests(unittest.TestCase):
    def test_minimax_matches_analytic_optimum(self):
        flows=[{"id":"a","path":["x"],"remaining_mbit":10}, {"id":"b","path":["x"],"remaining_mbit":30}]
        rates=allocate(flows,{"x":10})
        self.assertAlmostEqual(rates["a"],2.5,places=6)
        self.assertAlmostEqual(rates["b"],7.5,places=6)
        self.assertLess(max(f["remaining_mbit"]/rates[f["id"]] for f in flows),
                        max(f["remaining_mbit"]/allocate(flows,{"x":10},"equal")[f["id"]] for f in flows))

    def test_all_policies_respect_shared_links(self):
        flows=[{"id":"a","path":["x","y"],"remaining_mbit":10},
               {"id":"b","path":["x"],"remaining_mbit":20},
               {"id":"c","path":["y"],"remaining_mbit":5}]
        for policy in ("equal","demand","minimax"):
            rates=allocate(flows,{"x":8,"y":3},policy)
            assert_capacity(flows,rates,{"x":8,"y":3})
            self.assertTrue(all(v>0 for v in rates.values()))

    def test_zero_capacity_and_empty(self):
        self.assertEqual(allocate([],{}),{})
        self.assertEqual(allocate([{"id":"a","path":["x"],"remaining_mbit":10}],{"x":0}),{"a":0})

    def test_invalid_inputs_rejected(self):
        for capacities in ({"x":-1},{"x":float("nan")}):
            with self.assertRaises(ValueError): allocate([],capacities)
        with self.assertRaises(ValueError): allocate([{"id":"a","path":["x","x"],"remaining_mbit":1}],{"x":1})
        with self.assertRaises(ValueError): allocate([{"id":"a","path":["x"],"remaining_mbit":1}],{"y":1})

    def test_overhead_changes_optimum(self):
        flows=[{"id":"a","path":["x"],"remaining_mbit":10,"overhead_s":2},
               {"id":"b","path":["x"],"remaining_mbit":10,"overhead_s":0}]
        rates=allocate(flows,{"x":10})
        self.assertAlmostEqual(2+10/rates["a"],10/rates["b"],places=6)


class DataAndRoutingTests(unittest.TestCase):
    def setUp(self): self.config=ExperimentConfig(samples_per_client=120,rounds=2,network_ticks=25,flow_count=6)

    def test_topology_has_four_layers_and_alternate_paths(self):
        graph=public_topology()
        self.assertEqual(len(graph["nodes"]),12)
        self.assertEqual({n["layer"] for n in graph["nodes"]},{"GROUND","AIR","SPACE","SEA"})
        route=shortest_path("SEA1","EDGE",edge_costs(0,self.config,"static"))
        self.assertIsNotNone(route)
        self.assertEqual(len(route["nodes"]),len(set(route["nodes"])))

    def test_no_path_and_invalid_endpoints(self):
        self.assertIsNone(shortest_path("G1","EDGE",{}))
        with self.assertRaises(ValueError): shortest_path("unknown","EDGE",{})

    def test_outage_is_masked(self):
        self.assertFalse(channel(LINKS[1],30,42,"mixed")["active"])
        self.assertNotIn("L01",edge_costs(30,self.config,"current"))

    def test_deterministic_chronological_split(self):
        rows=generate("G1",self.config)
        self.assertEqual(rows,generate("G1",self.config))
        groups={s:[r for r in rows if r["split"]==s] for s in ("train","validation","test")}
        self.assertLess(max(r["tick"]+1 for r in groups["train"]), min(r["tick"]-1 for r in groups["validation"]))
        self.assertLess(max(r["tick"]+1 for r in groups["validation"]), min(r["tick"]-1 for r in groups["test"]))

    def test_inference_features_do_not_contain_target(self):
        row=feature_row(LINKS[0],"GROUND",10,42,"mixed",65536)
        self.assertNotIn("target_ms",row)
        self.assertNotIn("future",row)

    def test_reconnected_link_uses_explicit_cold_start_history(self):
        row=feature_row(LINKS[1],"GROUND",36,42,"mixed",65536)
        self.assertFalse(row["history_valid"])
        self.assertEqual(row["previous_delay_ms"],row["observed_delay_ms"])
        self.assertEqual(row["delta_load"],0)

    def test_no_cross_client_links_in_non_iid(self):
        ids={e.id for e in LINKS if "SEA1" in (e.source,e.target)}
        self.assertTrue(all(r["link_id"] in ids for r in generate("SEA1",self.config)))

    def test_network_policy_workloads_paired_and_capacity_safe(self):
        a=simulate(self.config,DelayModel(),"current","equal")
        b=simulate(self.config,DelayModel(),"fl","minimax")
        self.assertEqual([(f["id"],f["arrival"],f["size_mbit"]) for f in a["flows"]],
                         [(f["id"],f["arrival"],f["size_mbit"]) for f in b["flows"]])
        self.assertEqual(a["summary"]["capacity_violations"],0)
        self.assertEqual(b["summary"]["capacity_violations"],0)
        self.assertGreater(a["summary"]["evaluation_start_tick"],self.config.samples_per_client)
        for flow in b["flows"]:
            self.assertLessEqual(flow["delivered_mbit"],flow["size_mbit"]+1e-7)


class FedAvgAndCheckpointTests(unittest.TestCase):
    def test_weighted_average_is_exact(self):
        actual=FedAvg.aggregate([{"w":torch.tensor([2.])},{"w":torch.tensor([8.])}],[1,3])
        self.assertEqual(actual["w"].item(),6.5)

    def test_invalid_counts_and_shapes(self):
        for counts in ([0],[]):
            with self.assertRaises(ValueError): FedAvg.aggregate([{"w":torch.ones(1)}],counts)
        with self.assertRaises(ValueError): FedAvg.aggregate([{"w":torch.ones(1)},{"w":torch.ones(2)}],[1,1])

    def test_checkpoint_roundtrip_and_version_guard(self):
        row=generate("G1",ExperimentConfig(samples_per_client=80))[0]
        model=DelayModel(); restored=validate_envelope(envelope(model))
        self.assertEqual(predictions(model,[row]),predictions(restored,[row]))
        broken=envelope(model);broken["target"]="fl_rtt"
        with self.assertRaises(ValueError): validate_envelope(broken)

    def test_nonfinite_tensor_rejected(self):
        value=envelope(DelayModel());value["state"]["layers.4.bias"]=[float("nan")]
        with self.assertRaises(ValueError): validate_envelope(value)

    def test_atomic_artifact_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"nested"/"value.json"
            write_json(path,{"value":3});self.assertEqual(read_json(path),{"value":3})
            self.assertFalse(list(path.parent.glob("*.tmp")))


class ClientProtocolTests(unittest.TestCase):
    def setUp(self):
        self.config=ExperimentConfig(samples_per_client=80,local_epochs=1,model_family="residual_mlp",transport_codec="json")
        raw=generate("G1",self.config)
        data={s:[r for r in raw if r["split"]==s] for s in ("train","validation","test")}
        self.client=TestClient(create_client("G1",self.config,Path("a"*32)/"clients"/"G1","secret",{},data))
        self.headers={"Authorization":"Bearer secret"}
        self.model=envelope(DelayModel())

    def test_unauthorized_and_raw_endpoint_absent(self):
        self.assertEqual(self.client.get("/health").status_code,401)
        self.assertEqual(self.client.get("/raw",headers=self.headers).status_code,404)
        self.assertEqual(self.client.get("/export",headers=self.headers).status_code,404)

    def test_duplicate_training_idempotent_and_conflict_rejected(self):
        body={"round":1,"model":self.model}
        a=self.client.post("/train",json=body,headers=self.headers)
        self.assertEqual(a.status_code,200,a.text)
        b=self.client.post("/train",json=body,headers=self.headers)
        self.assertEqual(a.json(),b.json())
        conflict=copy.deepcopy(body);conflict["model"]["state"]["layers.4.bias"]=[1.]
        self.assertEqual(self.client.post("/train",json=conflict,headers=self.headers).status_code,409)

    def test_stale_and_extra_fields_rejected(self):
        self.assertEqual(self.client.post("/train",json={"round":2,"model":self.model},headers=self.headers).status_code,200)
        self.assertEqual(self.client.post("/train",json={"round":1,"model":self.model},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post("/train",json={"round":3,"model":self.model,"raw":[]},headers=self.headers).status_code,422)

    def test_evaluation_only_returns_aggregate_metrics(self):
        response=self.client.post("/evaluate",json={"model":self.model,"split":"test","local_epochs":1},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn("rows",response.json())
        self.assertNotIn("target_ms",response.text)
        self.assertIn("local_only",response.json())


if __name__=="__main__": unittest.main()
