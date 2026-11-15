from dataclasses import dataclass
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, solve, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import AMBIENT_C, die_peaks_c  # noqa: E402
from boost_headroom import B_HIGH, b_max, compare, die_rise_matrix, scale_for_margin, verdict  # noqa: E402
from robust_modes import modes  # noqa: E402


@dataclass
class FakeProblem:
    names: list
    power_w: np.ndarray


class BoostHeadroomTest(unittest.TestCase):
    def test_unit_responses_reproduce_the_die_peaks(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        rise = die_rise_matrix(problem, layout, 0., 64)
        _, field, edges = solve(thermal_case_data(problem, layout, 0.))
        expected = die_peaks_c(problem, layout, field, edges)
        got = [float((problem.power_w @ r).max()) + AMBIENT_C for r in rise]
        np.testing.assert_allclose(got, expected, atol=1e-9)

    def test_b_max_is_the_largest_cap_that_keeps_every_mode_within_limits(self):
        # Two CPUs, 1 K/W self-heating only; idling one hands its power to the other up to b x nominal.
        problem = FakeProblem(['CPU1_0', 'CPU1_1', 'CPU1_2', 'CPU1_3'], np.full(4, 10.))
        rise = [np.eye(4)[:, [k]] for k in range(4)]
        limit = np.full(4, 105.)
        # Full load: 10 K rise; a die reaches its limit (60 K rise) at power 60 W, i.e. b = 6 at scale 1;
        # at scale 4 a die sits at 40 W (85 C) and fails above b = 1.5.
        self.assertAlmostEqual(b_max(rise, problem, 4., limit), 1.5, places=3)
        self.assertEqual(b_max(rise, problem, 1., limit), B_HIGH)
        self.assertIsNone(b_max(rise, problem, 7., limit))
        self.assertTrue(len(modes(problem, 1.5)[0]) > 1)

    def test_scale_baseline_and_verdict(self):
        self.assertAlmostEqual(scale_for_margin(np.array([30., 10.]), np.array([105., 95.]), 5.), 55/30)
        length = np.array([10., 11., 12., 20.])
        full_scale = np.array([1.0, .98, .9, 1.2])
        r = compare(length, 12.5, full_scale, [1.2, 1.4, None, 2.0], 0)
        self.assertEqual(r['robust_best'], 1)
        self.assertAlmostEqual(r['gain_b'], .2)
        self.assertAlmostEqual(r['full_load_scale_ratio'], .98)
        self.assertEqual(verdict([.1, .2, .15, 0.]), 'worthwhile')
        self.assertEqual(verdict([.01, 0.]), 'degenerate')
        self.assertEqual(verdict([]), 'no_data')


if __name__ == '__main__':
    unittest.main()
