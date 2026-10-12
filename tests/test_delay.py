import unittest

from backend.services.delay_service import estimate_communication_ms


class DelayEstimateTests(unittest.TestCase):
    def test_estimates_two_way_model_transfer_with_profile(self):
        self.assertAlmostEqual(estimate_communication_ms(2, 1, 0.5), 8004)
        self.assertAlmostEqual(estimate_communication_ms(2, 1, 0.5, "high_latency"), 8040)
        self.assertAlmostEqual(estimate_communication_ms(2, 1, 0.5, "low_bandwidth"), 80004)

    def test_clamps_missing_or_invalid_network_capacity(self):
        self.assertEqual(estimate_communication_ms(-5, 0, 0, "normal"), 0)


if __name__ == "__main__":
    unittest.main()
