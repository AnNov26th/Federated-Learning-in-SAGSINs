import unittest

from backend.services.scheduling_service import select_clients


class ClientSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "slow": {"status": "ACTIVE", "latency": 10, "bandwidth": 0.1},
            "fast": {"status": "ACTIVE", "latency": 5, "bandwidth": 10},
            "medium": {"status": "ACTIVE", "latency": 8, "bandwidth": 5},
            "offline": {"status": "OFFLINE", "latency": 0, "bandwidth": 100},
        }

    def test_delay_aware_selects_fastest_active_clients(self):
        selected = select_clients(
            "DelayAware", list(self.profiles), self.profiles, 2,
            seed=42, round_number=1, model_size_mb=0.5,
        )
        self.assertEqual(selected, ["fast", "medium"])

    def test_fedavg_sampling_is_repeatable_and_excludes_inactive_nodes(self):
        first = select_clients(
            "FedAvg", list(self.profiles), self.profiles, 2,
            seed=42, round_number=1, model_size_mb=0.5,
        )
        second = select_clients(
            "FedAvg", list(reversed(self.profiles)), self.profiles, 2,
            seed=42, round_number=1, model_size_mb=0.5,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertNotIn("offline", first)

    def test_delay_aware_breaks_equal_scores_by_node_id(self):
        tied = {"B": self.profiles["fast"], "A": self.profiles["fast"]}
        self.assertEqual(
            select_clients("DelayAware", ["B", "A"], tied, 1, 3, 1, 0.1),
            ["A"],
        )

    def test_fails_when_active_candidate_pool_is_too_small(self):
        with self.assertRaisesRegex(ValueError, "Only 1 ACTIVE"):
            select_clients("DelayAware", ["fast", "offline"], self.profiles, 2, 1, 1, 0.5)


if __name__ == "__main__":
    unittest.main()
