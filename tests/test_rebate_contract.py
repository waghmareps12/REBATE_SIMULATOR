import itertools
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import rebate_contract as rc


ROOT = Path(__file__).resolve().parents[1]


def synthetic_data() -> rc.AccountPeriodData:
    return rc.AccountPeriodData.from_frame(
        pd.DataFrame(
            [
                {"rfp_name": "A", "rfp_group": 1, "prevyr_rev": 100, "curryr_rev": 120},
                {"rfp_name": "A", "rfp_group": 2, "prevyr_rev": 200, "curryr_rev": 220},
                {"rfp_name": "A", "rfp_group": 3, "prevyr_rev": 100, "curryr_rev": 150},
                {"rfp_name": "A", "rfp_group": 4, "prevyr_rev": 200, "curryr_rev": 300},
            ]
        )
    )


class AccountPreparationTests(unittest.TestCase):
    def test_aggregates_composite_account_and_reconciles_source(self):
        source = pd.DataFrame(
            [
                {"rfp_name": "A", "rfp_group": 1, "prevyr_rev": 40, "curryr_rev": 50},
                {"rfp_name": "A", "rfp_group": 1, "prevyr_rev": 60, "curryr_rev": 70},
                {"rfp_name": "B", "rfp_group": 1, "prevyr_rev": 100, "curryr_rev": 130},
            ]
        )
        data = rc.AccountPeriodData.from_frame(source)
        self.assertEqual(data.source_rows, 3)
        self.assertEqual(len(data.accounts), 2)
        account = data.accounts.query("rfp_name == 'A'").iloc[0]
        self.assertEqual(account.baseline_revenue, 100)
        self.assertEqual(account.forecast_revenue, 120)
        self.assertAlmostEqual(account.growth, 0.2)

    def test_missing_columns_are_actionable(self):
        with self.assertRaisesRegex(ValueError, "Missing required columns"):
            rc.AccountPeriodData.from_frame(pd.DataFrame({"curryr_rev": [1]}))


class ContractRuleTests(unittest.TestCase):
    def setUp(self):
        self.data = synthetic_data()
        self.config = rc.ProgramConfig(
            name="test",
            volume_milestones=(120, 220),
            growth_milestones=(0.1, 0.5),
            min_accounts_per_cell=1,
            min_revenue_share_per_cell=0,
            min_rate=0.01,
            max_rate=0.03,
            rate_step=0.01,
            min_increment=0.01,
            max_migration_net_impact=1,
        )

    def test_exact_thresholds_are_inclusive_and_highest_attained_wins(self):
        vi, gi, eligible, _ = rc.assign_cells(self.data.accounts, self.config)
        by_id = {
            int(row.rfp_group): (vi[index], gi[index], eligible[index])
            for index, row in self.data.accounts.iterrows()
        }
        self.assertEqual(by_id[1], (0, 0, True))
        self.assertEqual(by_id[2], (1, 0, True))
        self.assertEqual(by_id[3], (0, 1, True))
        self.assertEqual(by_id[4], (1, 1, True))

    def test_incremental_payout_matches_hand_calculation(self):
        rates = [[0.01, 0.02], [0.02, 0.03]]
        result = rc.evaluate_actual_grid(self.data, self.config, rates)
        expected = 0.01 * 20 + 0.02 * 20 + 0.02 * 50 + 0.03 * 100
        self.assertAlmostEqual(result["total_payout"], expected)
        self.assertEqual(result["eligible_accounts"], 4)

    def test_all_revenue_basis_is_available_for_comparison(self):
        config = replace(self.config, payout_basis="all_revenue")
        result = rc.evaluate_actual_grid(self.data, config, [[0.01, 0.02], [0.02, 0.03]])
        expected = 0.01 * 120 + 0.02 * 220 + 0.02 * 150 + 0.03 * 300
        self.assertAlmostEqual(result["total_payout"], expected)

    def test_zero_baseline_and_below_threshold_are_reconciled(self):
        source = pd.DataFrame(
            [
                {"rfp_name": "A", "rfp_group": 1, "prevyr_rev": 0, "curryr_rev": 200},
                {"rfp_name": "A", "rfp_group": 2, "prevyr_rev": 100, "curryr_rev": 80},
                {"rfp_name": "A", "rfp_group": 3, "prevyr_rev": 100, "curryr_rev": -10},
            ]
        )
        data = rc.AccountPeriodData.from_frame(source)
        _, _, eligible, exclusions = rc.assign_cells(data.accounts, self.config)
        self.assertEqual(int(eligible.sum()), 0)
        self.assertEqual(exclusions["new_or_nonpositive_baseline"], 1)
        self.assertEqual(exclusions["negative_or_invalid_forecast"], 1)
        self.assertEqual(exclusions["below_volume_milestone"], 1)
        self.assertEqual(sum(exclusions.values()), 3)


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.data = synthetic_data()
        self.config = rc.ProgramConfig(
            name="tiny",
            volume_milestones=(120, 220),
            growth_milestones=(0.1, 0.5),
            min_accounts_per_cell=1,
            min_revenue_share_per_cell=0,
            min_rate=0.01,
            max_rate=0.03,
            rate_step=0.01,
            min_increment=0.01,
            max_migration_net_impact=1,
        )
        self.scenarios = rc.ScenarioSet(low=1.0, base=1.5, high=2.0)

    def _net_for_grid(self, rates):
        accounts = self.data.accounts
        vi, gi, eligible, _ = rc.assign_cells(accounts, self.config)
        total = 0.0
        for index, row in accounts.iterrows():
            if not eligible[index]:
                total += max(row.forecast_revenue, 0)
                continue
            rate = rates[gi[index], vi[index]]
            projected = row.forecast_revenue * (1 + 1.5 * rate)
            payout = rate * max(projected - row.baseline_revenue, 0)
            total += projected - payout
        return total

    def test_milp_matches_exhaustive_search_on_tiny_grid(self):
        result = rc.optimize_program(self.data, [self.config], self.scenarios)
        allowed = self.config.allowed_rates
        feasible = []
        for values in itertools.product(allowed, repeat=4):
            grid = np.asarray(values).reshape(2, 2)
            if np.all(np.diff(grid, axis=0) >= 0.01 - 1e-9) and np.all(
                np.diff(grid, axis=1) >= 0.01 - 1e-9
            ):
                feasible.append((self._net_for_grid(grid), grid))
        exhaustive_net, _ = max(feasible, key=lambda item: item[0])
        self.assertAlmostEqual(result.scenarios["base"]["net_revenue"], exhaustive_net)
        self.assertTrue(all(result.constraint_checks.values()))

    def test_sparse_candidate_is_rejected_with_cell_reason(self):
        sparse = replace(self.config, min_accounts_per_cell=2)
        assessment = rc.assess_candidate(self.data, sparse)
        self.assertFalse(assessment.accepted)
        self.assertIn("minimum is 2", assessment.reasons[0])

    def test_budget_is_enforced_or_reported_infeasible(self):
        infeasible = replace(self.config, budget=0)
        with self.assertRaisesRegex(ValueError, "No candidate satisfied"):
            rc.optimize_program(self.data, [infeasible], self.scenarios)

    def test_legacy_objectives_have_expected_degenerate_direction(self):
        revenues = np.array([100.0, 200.0])
        low_rates = np.array([0.01, 0.02])
        high_rates = np.array([0.05, 0.06])
        legacy_random_low = revenues.sum() - np.sum(revenues * low_rates)
        legacy_random_high = revenues.sum() - np.sum(revenues * high_rates)
        self.assertGreater(legacy_random_low, legacy_random_high)

        elasticity = 2.0
        objective = lambda rate: (1 + elasticity * rate) * (1 - rate)
        self.assertGreater(objective(0.15), objective(0.10))


class DatasetAcceptanceTests(unittest.TestCase):
    def test_full_dataset_reconciles_and_default_run_is_deterministic(self):
        data = rc.AccountPeriodData.from_csv(ROOT / "DummyDataGpot2.csv")
        self.assertEqual(data.reconciliation()["source_rows"], 9802)
        first = rc.optimize_default_program(data)
        second = rc.optimize_default_program(data)
        np.testing.assert_array_equal(first.rates, second.rates)
        self.assertEqual(first.reconciliation["aggregated_accounts"], 9802)
        self.assertTrue(all(first.constraint_checks.values()))
        self.assertTrue(first.migration["stable"])


if __name__ == "__main__":
    unittest.main()
