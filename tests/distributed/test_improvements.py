import base64
import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import zlib
import torch
from sagsin.allocation import allocate, assert_capacity
from sagsin.config import ExperimentConfig
from sagsin.dataset import generate
from sagsin.model import DelayModel, envelope, predictions, train, validate_envelope
from sagsin.simulation import simulate
from sagsin.storage import write_json,read_json


class PackedTensorTests(unittest.TestCase):
    def test_both_families_are_bit_exact_after_packing(self):
        for family in ("residual_mlp","trend"):
            original=DelayModel(family)
            with torch.no_grad():
                for p in original.parameters():p.uniform_(-.25,.25)
            restored=validate_envelope(envelope(original,"packed"))
            for key,value in original.state_dict().items():
                self.assertTrue(torch.equal(value,restored.state_dict()[key]))

    def test_legacy_dense_checkpoint_loads(self):
        original=envelope(DelayModel())
        original.pop("model_family")
        self.assertEqual(validate_envelope(original).family,"residual_mlp")

    def test_packed_rejects_trailing_truncated_and_bomb_data(self):
        value=envelope(DelayModel("trend"),"packed")
        bad=copy.deepcopy(value)
        bad["state"]=base64.b64encode(zlib.compress(b"x"*100000)).decode()
        with self.assertRaises(ValueError):validate_envelope(bad)
        for payload in ("not-base64!",value["state"][:-4],base64.b64encode(base64.b64decode(value["state"])+b"extra").decode()):
            bad=dict(value,state=payload)
            with self.assertRaises(ValueError):validate_envelope(bad)

    def test_mlp_packed_is_smaller_than_json(self):
        model=DelayModel()
        plain=len(json.dumps(envelope(model),separators=(",",":")).encode())
        packed=len(json.dumps(envelope(model,"packed"),separators=(",",":")).encode())
        self.assertLess(packed,plain*.5)

    def test_config_legacy_read_preserves_old_family(self):
        old={"rounds":3,"seed":42}
        self.assertEqual(ExperimentConfig.from_saved(old).model_family,"residual_mlp")
        self.assertEqual(ExperimentConfig.from_saved(old).transport_codec,"json")
        self.assertEqual(ExperimentConfig().model_family,"trend")


class PredictorTests(unittest.TestCase):
    def test_trend_starts_at_persistence_and_trains(self):
        torch.set_num_threads(1)
        rows=generate("G1",ExperimentConfig(samples_per_client=160))
        model=DelayModel("trend")
        self.assertEqual(sum(p.numel() for p in model.parameters()),4)
        before=predictions(model,rows[:3])
        for actual,row in zip(before,rows[:3]):self.assertAlmostEqual(actual,row["observed_delay_ms"],places=3)
        part=[r for r in rows if r["split"]=="train"]
        train(model,part,2,.02,32,211)
        self.assertTrue(any(abs(float(v))>1e-6 for v in model.trend.weight.detach().flatten()))


class ByteBaselineTests(unittest.TestCase):
    def test_posthoc_baseline_counts_float32_and_never_retrains(self):
        from sagsin.offline import refresh_byte_baselines
        rows=[r for r in generate("G1",ExperimentConfig(samples_per_client=80)) if r["split"]=="train"]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            write_json(root/"result.json",{"clients":{"G1":{}},"communication":{"total_json_bytes":100}})
            write_json(root/"offline-baseline.json",{})
            with patch("sagsin.offline.credentials",return_value={"clients":{"G1":{}}}),patch("sagsin.offline.load_local",return_value=rows),patch("sagsin.offline.train",side_effect=AssertionError("Unexpected training")):
                value=refresh_byte_baselines(root)
            self.assertEqual(value["one_time_upload_bytes"]["training_float32"],len(rows)*16*4)
            self.assertEqual(value["inclusive_savings_by_baseline"]["training_float32"],1-100/(len(rows)*16*4))
            self.assertEqual(set(p.name for p in root.iterdir()),{"result.json","offline-baseline.json"})


class DeadlineTests(unittest.TestCase):
    def test_impossible_flow_does_not_starve_finishable_flow(self):
        flows=[{"id":"short","path":["x"],"remaining_mbit":2.,"time_left_s":2.5},
               {"id":"impossible","path":["x"],"remaining_mbit":10.,"time_left_s":2.5}]
        result=allocate(flows,{"x":1.},"deadline")
        self.assertAlmostEqual(result["short"],1)
        self.assertEqual(result["impossible"],0)
        assert_capacity(flows,result,{"x":1.})

    def test_admission_preserves_shared_link_capacity(self):
        flows=[{"id":"a","path":["x","y"],"remaining_mbit":5.,"time_left_s":3.},
               {"id":"b","path":["x"],"remaining_mbit":5.,"time_left_s":4.},
               {"id":"c","path":["y"],"remaining_mbit":4.,"time_left_s":1.}]
        result=allocate(flows,{"x":3.,"y":2.},"deadline")
        assert_capacity(flows,result,{"x":3.,"y":2.})
        self.assertTrue(all(v>=0 for v in result.values()))

    def test_deadline_requires_finite_time(self):
        with self.assertRaises(ValueError):allocate([{"id":"a","path":["x"],"remaining_mbit":2}],{"x":3},"deadline")

    def test_simulation_accounts_for_deferred_flows_and_safe_reroute(self):
        cfg=ExperimentConfig(samples_per_client=120,network_ticks=30,flow_count=12,reroute_improvement=.05)
        result=simulate(cfg,DelayModel("trend"),"fl","deadline")
        self.assertEqual(result["summary"]["capacity_violations"],0)
        self.assertTrue(all(a["information_time"]==a["tick"] for a in result["audit"] if a["kind"]=="route"))
        for f in result["flows"]:
            self.assertLessEqual(f["delivered_mbit"],f["size_mbit"]+1e-6)


if __name__=="__main__":unittest.main()
