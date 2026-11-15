from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from cold_plate_joint import FIT_FLOWS_LPM, compare, fit, needed_flow, verdict  # noqa: E402
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import FLOW_DIRECTIONS, solve_cold_plate  # noqa: E402

Q = np.array(FIT_FLOWS_LPM)


class ColdPlateJointTest(unittest.TestCase):
    def test_fit_recovers_the_inverse_flow_law_and_the_needed_flow(self):
        alpha, beta, error = fit(80. + 6./Q)
        self.assertAlmostEqual(float(alpha), 80.)
        self.assertAlmostEqual(float(beta), 6.)
        self.assertLess(float(error), 1e-9)
        self.assertAlmostEqual(float(needed_flow(alpha, beta, 86.)), 1.)
        self.assertEqual(float(needed_flow(alpha, beta, 79.)), np.inf)  # below the infinite-flow limit

    def test_compare_takes_the_coolest_layout_within_each_cap(self):
        caps = {'1.0': 10., '1.25': 12.5}
        rows = compare(caps, np.array([10., 12.]), np.array([90., 88.]), np.array([10., 12., 11.]),
                       np.array([90., 88., 86.5]))
        self.assertEqual((rows['1.0']['gain_k'], rows['1.25']['gain_k']), (0., 1.5))
        self.assertEqual(rows['1.25']['joint'], 2)
        self.assertIsNone(compare({'0.5': 5.}, np.array([10.]), np.array([90.]), np.array([10.]), np.array([90.]))['0.5'])
        self.assertEqual(verdict([rows]*3), 'worthwhile')
        self.assertEqual(verdict([rows]*2), 'uncertain')
        self.assertEqual(verdict([{'1.0': rows['1.0'], '0.5': None}]), 'degenerate')

    def test_evaluator_scores_a_layout_with_its_best_flow_direction(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        flow = 2e-4
        data = thermal_case_data(problem, layout, 0., cold_plate_h_w_m2k=5000.)
        best = min(solve_cold_plate(data, flow, d)[0]['peak_power_layer_c'] for d in FLOW_DIRECTIONS)
        with Evaluator(problem, 0., 64, 1, (5000., flow)) as evaluator:
            self.assertEqual(evaluator.peaks_c([layout])[0], best)
            self.assertEqual(evaluator.solves, 1)


if __name__ == '__main__':
    unittest.main()
