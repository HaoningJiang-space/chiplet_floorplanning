import unittest

import numpy as np

from chiplet_floorplanning.placement.decision import worst_regret_bounds


class WorkloadInformationTests(unittest.TestCase):
    def test_pairwise_compatible_but_no_design_serves_three_loads(self):
        # Three sites; avoid the site already heating under this scenario.
        cost = np.eye(3)
        for omit in range(3):
            pair = np.delete(cost, omit, axis=0)
            self.assertEqual(worst_regret_bounds(pair, pair)[1].min(), 0.0)
        lo, hi = worst_regret_bounds(cost, cost)
        np.testing.assert_array_equal(lo, [1.0, 1.0, 1.0])
        np.testing.assert_array_equal(hi, lo)

    def test_oracle_retains_scenario_specific_feasible_designs(self):
        rows = [[2.0, 0.0, np.inf], [3.0, np.inf, 0.0]]
        lo, hi = worst_regret_bounds(rows, rows)
        np.testing.assert_equal(lo, [3.0, np.inf, np.inf])
        np.testing.assert_equal(hi, lo)
        np.testing.assert_equal(worst_regret_bounds([[0.0]], [[20.0]]), [[0.0], [0.0]])

    def test_overlap_is_undecided_and_zero_regret_excludes_self(self):
        lo, hi = worst_regret_bounds([[0.0, 1.0], [1.0, 0.0]], [[2.0, 1.0], [1.0, 2.0]])
        np.testing.assert_equal(lo, [0.0, 0.0])
        np.testing.assert_equal(hi, [1.0, 1.0])
