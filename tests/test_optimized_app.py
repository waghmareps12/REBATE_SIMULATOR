import unittest

import optimized_app


class OptimizedAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        optimized_app.app.config.update(TESTING=True)
        cls.client = optimized_app.app.test_client()

    def test_health_reconciles_dataset(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reconciliation"]["source_rows"], 9802)

    def test_optimize_returns_contract_and_diagnostics(self):
        response = self.client.post(
            "/optimize",
            json={
                "volume_milestones": [6500, 25000, 50000],
                "growth_milestones": [0.06, 0.10, 0.15, 0.20],
                "payout_basis": "incremental",
                "include_auto_candidates": True,
                "scenarios": {"low": 0.5, "base": 1.5, "high": 2.5},
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(len(payload["rates"]), 4)
        self.assertEqual(len(payload["rates"][0]), 3)
        self.assertTrue(payload["constraint_checks"]["low_scenario_guard"])
        rejected = {item["name"]: item for item in payload["candidate_assessments"]}
        self.assertFalse(rejected["user_grid"]["accepted"])
        self.assertIn("legacy_current_grid", rejected)

    def test_invalid_scenario_order_returns_400(self):
        response = self.client.post(
            "/optimize",
            json={"scenarios": {"low": 2, "base": 1, "high": 3}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("low <= base <= high", response.get_json()["error"])

    def test_static_calculator_validates_shape(self):
        response = self.client.post(
            "/calculate_static",
            json={
                "volume_milestones": [6500, 25000, 50000],
                "growth_milestones": [0.06, 0.10, 0.15, 0.20],
                "rates": [[0.01]],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("shape", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
