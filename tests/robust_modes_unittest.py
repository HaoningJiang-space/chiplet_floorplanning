from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem, solve, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import die_peaks_c  # noqa: E402
from robust_modes import compare, limits, modes, verdict  # noqa: E402
from workload_leverage import budget_power  # noqa: E402


class RobustModesTest(unittest.TestCase):
    def test_evaluator_scores_the_worst_overshoot_over_modes_and_dies(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        rows = np.array([problem.power_w, problem.power_w*[2., .5]])
        limit = np.array([50., 47.])
        expected = []
        for p in rows:
            q = replace(problem, power_w=p)
            _, rise, edges = solve(thermal_case_data(q, layout, 0.))
            expected.append(die_peaks_c(q, layout, rise, edges))
        expected = np.array(expected)
        with Evaluator(problem, 0., modes=(rows, limit)) as evaluator:
            j = evaluator.peaks_c([layout])[0]
            die = evaluator.die_peaks_c([layout])[0]
        self.assertAlmostEqual(j, (expected - limit).max(), places=9)
        np.testing.assert_allclose(die, expected.max(0), atol=1e-9)

    def test_modes_keep_the_package_budget_and_boost_one_only_lowers_power(self):
        names = ['CPU1_0', 'CPU1_1', 'GPU_0', 'GPU_1', 'HBM_0']
        problem = type('P', (), dict(names=names, power_w=np.array([10., 10., 40., 40., 20.])))
        for boost in (1.0, 1.5):
            m, rows = modes(problem, boost)
            self.assertEqual(m[0], 'nominal')
            self.assertTrue((rows.sum(1) <= problem.power_w.sum() + 1e-9).all())
            self.assertTrue((rows <= boost*problem.power_w + 1e-9).all())
        self.assertTrue((modes(problem, 1.0)[1] <= problem.power_w + 1e-12).all())
        self.assertEqual(limits(names).tolist(), [105., 105., 105., 105., 95.])

    def test_gain_feasibility_and_reverse_cost_within_the_cap(self):
        length = np.array([10., 12., 12.4, 20.])
        nominal = np.array([100., 98., 99., 90.])
        j = np.array([5., 3., -1., -9.])
        r = compare(length, nominal, j, 12.5, 1)
        self.assertEqual(r['robust_best'], 2)
        with self.assertRaises(ValueError):          # a baseline over the interconnect cap is rejected
            compare(length, nominal, j, 12.5, 3)
        self.assertAlmostEqual(r['gain_k'], 4.)
        self.assertAlmostEqual(r['reverse_cost_k'], 1.)
        self.assertEqual((r['feasible_baseline'], r['feasible_robust_best']), (False, True))
        self.assertEqual(verdict([1., 1.5, 0.]), 'worthwhile')
        self.assertEqual(verdict([1., 0.5, 0.]), 'uncertain')
        self.assertEqual(verdict([]), 'no_data')

    def test_zero_power_dies_receive_no_freed_power(self):
        power = budget_power(np.array([2.5, 0.]), np.array([.2, 1.]), np.array([True, True]))
        np.testing.assert_allclose(power, [.5, 0.])


if __name__ == '__main__':
    unittest.main()
