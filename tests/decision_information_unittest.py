import unittest

import numpy as np

from chiplet_floorplanning.placement.decision import (
    ThermalCandidate, guaranteed_amplitude, search_thermal_targets, worst_regret_bounds,
)
from chiplet_floorplanning.placement.problem import Layout


class WorkloadInformationTests(unittest.TestCase):
    def test_power_radius_checks_all_cells_including_static_hotspots(self):
        self.assertEqual(guaranteed_amplitude([90, 87], [0, 2], 91, 10), 2)
        self.assertIsNone(guaranteed_amplitude([92, 87], [0, 2], 91, 10))
        self.assertEqual(guaranteed_amplitude([90], [0], 91, 10), 10)

    def test_search_moves_for_relative_excess_and_charges_both_scenarios(self):
        def point(x, peaks):
            layout = Layout(np.array([[float(x), 0.]]), np.array([0]))
            return ThermalCandidate(layout, 1., np.array(peaks), np.array(peaks)[:, None])

        anchor = point(0, [88., 103.])
        first = point(1, [86., 105.])
        second = point(2, [89., 100.])
        sequence = iter([anchor.layout, first.layout, second.layout])
        observations = []

        def propose(parent, die_peaks):
            observations.append(float(die_peaks[0]))
            return next(sequence)

        points = {1: first, 2: second}
        _, result, trials = search_thermal_targets(
            [anchor], [84., 102.], propose, lambda l: points[int(l.centre_um[0,0])], budget=5)
        self.assertIs(result, first)
        self.assertEqual(observations, [88., 88., 105.])
        self.assertEqual([t[-1] for t in trials], [True, False])

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
