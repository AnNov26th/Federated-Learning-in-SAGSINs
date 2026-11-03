import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sagsin.acceptance_matrix import paired_interval, summarize
from sagsin.service_route_benchmark import evaluate, POLICIES
from sagsin.model import DelayModel, envelope
from sagsin.storage import write_json


class AcceptanceStatisticsTests(unittest.TestCase):
    def test_intervals_sample_seeds_and_handle_missing_data(self):
        self.assertEqual(paired_interval([])['ci95'], None)
        self.assertEqual(paired_interval([3])['ci95'], None)
        self.assertEqual(paired_interval([2, 2, 2, 2, 2])['ci95'], [2, 2])
        values = [-1, 0, 1, 2, 3]
        self.assertEqual(paired_interval(values), paired_interval(values))

    def test_paired_delta_preserves_direction_and_missing_latency(self):
        from sagsin.acceptance_matrix import METRICS
        rows = []
        for seed in (11, 42):
            for policy in POLICIES:
                r = dict(case='outage', seed=seed, policy=policy)
                r.update({m: None if m == 'mean_one_way_ms' else (1 if policy == 'predictive' else 2) for m in METRICS})
                rows.append(r)
        aggregates, paired = summarize(rows)
        self.assertEqual(len(aggregates), 3)
        qos = next(p for p in paired if p['baseline'] == 'current' and p['metric'] == 'qos_fraction')
        self.assertEqual(qos['mean'], -1)
        delay = next(p for p in paired if p['metric'] == 'mean_one_way_ms')
        self.assertEqual(delay['n'], 0)


class AcceptanceCapacityTests(unittest.TestCase):
    def test_two_directions_share_access_and_pause_reduces_delivery(self):
        nodes = [SimpleNamespace(id=k, type='GROUND', status='ACTIVE', lat=0, lng=i, bandwidth=100)
                 for i, k in enumerate(('A', 'B'))]
        def frame(inventory, links, now, *args):
            return dict(nodes={n.id:n for n in inventory}, edges={}, now=now)
        def route(*args):
            return dict(path=['A', 'B'], hops=[dict(link_id='AB', bandwidth_mbps=100)],
                        sourceCapacityMbps=2, receiver_capacity_mbps=2,
                        application=dict(estimated_one_way_ms=10), path_stretch=1), 'ok'
        checkpoint = dict(model=envelope(DelayModel('trend')))
        result = dict(config=dict(seed=42, samples_per_client=40, profile='normal'))
        with patch('sagsin.service_route_benchmark.build_frame', side_effect=frame), \
             patch('sagsin.service_route_benchmark.route', side_effect=route), \
             patch('sagsin.service_route_benchmark.refresh_route', side_effect=lambda f,r,*a:r):
            rows, _ = evaluate(nodes, [], result, checkpoint, seconds=1, pairs_count=1, handover_pause=.1)
        for row in rows:
            self.assertAlmostEqual(row['delivery_fraction'], .45)
            self.assertEqual(row['qos_fraction'], 0)
            self.assertEqual(row['capacity_violations'], 0)


class AcceptanceCollectionTests(unittest.TestCase):
    def test_collection_requires_every_policy_and_refuses_duplicates(self):
        from sagsin.acceptance_matrix import collect
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package=root/'input'; source=root/'worker'
            write_json(package/'models.json',[dict(seed=11,experiment_id=13)])
            write_json(package/'inventory.json',dict(nodes=[dict(id='A',type='GROUND',status='ACTIVE',lat=0,lng=0),
                                                          dict(id='B',type='GROUND',status='ACTIVE',lat=1,lng=1)]))
            write_json(source/'methodology.json',dict(complete=False))
            case=dict(name='normal',pairs=1,device='network_gateway')
            rows=[dict(case='normal',seed=11,policy=p,cases=30,experiment_id=13) for p in POLICIES]
            write_json(source/'runs.json',rows[:2])
            with self.assertRaisesRegex(ValueError,'Missing'):
                collect(package,root/'out',30,[case],[source])
            write_json(source/'runs.json',rows)
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                collect(package,root/'out',30,[case],[source,source])
            with patch('sagsin.acceptance_matrix.finish') as finish:
                collect(package,root/'out',30,[case],[source])
            self.assertEqual(len(finish.call_args.args[4]),3)
            self.assertEqual(len(finish.call_args.args[5]['normal:11']),1)
            self.assertFalse(finish.call_args.args[7][0]['source_complete'])


if __name__ == '__main__':
    unittest.main()
