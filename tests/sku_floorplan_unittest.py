from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import AMBIENT_C, power_layer_responses  # noqa: E402
from sku_floorplan import choose, group, tier_peaks, tiers, verdict  # noqa: E402


class SkuFloorplanTest(unittest.TestCase):
    def test_responses_superpose_to_the_full_solve(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        p = problem.power_w
        fields, _ = power_layer_responses(problem, layout, 0., [[p[0], 0], [0, p[1]]])
        full = solve_peak(thermal_case_data(problem, layout, 0.))['peak_power_layer_c']
        self.assertAlmostEqual(np.nanmax(fields.sum(0)) + AMBIENT_C, full, places=9)

    def test_tiers_follow_the_data_sheet_ratios(self):
        self.assertEqual(tiers(12), [('full', 12, 1.0), ('two_thirds', 8, 1.5), ('one_third', 4, 1.75)])
        self.assertEqual([m for _, m, _ in tiers(4)], [4, 3, 1])
        _, _, io = tiers(12, .25)[2]
        self.assertAlmostEqual(io, (210/360 - .25)/.75*3)

    def test_group_is_the_most_numerous_compute_kind(self):
        names = ['CPU1_0', 'CPU1_1', 'GPU_0', 'GPU_1', 'GPU_2', 'GPU_3', 'HBM_0', 'HBM_1', 'HBM_2', 'HBM_3', 'HBM_4']
        self.assertEqual(group(names, np.ones(len(names))).tolist(), [2, 3, 4, 5])
        self.assertIsNone(group(names[:5], np.ones(5)))

    def test_designed_takes_the_coolest_set_and_harvested_the_hottest(self):
        fixed = np.zeros(3)
        unit = np.array([[3., 0, 0], [0, 1., 0], [0, 0, 2.]])
        self.assertEqual(tier_peaks(fixed, unit, 1, 2.), (2. + AMBIENT_C, 6. + AMBIENT_C))

    def test_regret_and_reverse_cost_within_the_cap(self):
        length = np.array([10., 12., 12.4, 20.])
        full = np.array([70., 60., 61., 50.])
        objective = np.array([80., 75., 72., 60.])
        r = choose(length, full, objective)
        self.assertEqual((r['nominal_best'], r['sku_best']), (1, 2))
        self.assertAlmostEqual(r['regret_k'], 3.)
        self.assertAlmostEqual(r['reverse_cost_k'], 1.)
        self.assertEqual(verdict([1., 1.2, 3., 0.]), 'worthwhile')
        self.assertEqual(verdict([.1, .2]), 'degenerate')


if __name__ == '__main__':
    unittest.main()
