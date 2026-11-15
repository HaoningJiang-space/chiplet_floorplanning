from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from throughput_knob import X_MAX, X_MIN, allocate, die_cells, rank_correlation, verdict  # noqa: E402
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, thermal  # noqa: E402


class ThroughputKnobTest(unittest.TestCase):
    def test_unit_responses_superpose_to_the_full_solve(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        _, full, edges = thermal.solve(thermal.thermal_case_data(problem, layout, 0.))
        unit = [thermal.solve(thermal.thermal_case_data(replace(problem, power_w=np.eye(2)[i]), layout, 0.))[1]
                for i in range(2)]
        owner = die_cells(problem, layout, edges)
        superposed = problem.power_w @ np.array([u.ravel()[owner >= 0] for u in unit])
        self.assertTrue(np.allclose(superposed, full.ravel()[owner >= 0], atol=1e-9))
        self.assertEqual(set(owner[owner >= 0]), {0, 1})

    def test_per_die_knob_moves_power_to_the_die_with_thermal_room(self):
        # Two compute dies, one cell each, no coupling. Die 0 may reach 1.5x, die 1 only 0.5x.
        fields, owner = np.eye(2), np.array([0, 1])
        nominal, compute = np.array([10., 10.]), np.array([True, True])
        limit = 45. + np.array([15., 5.])
        t, x = allocate(fields, owner, nominal, compute, limit)
        self.assertTrue(np.allclose(x, [X_MAX, .5], atol=1e-9))
        self.assertAlmostEqual(t, 10*(X_MAX**(1/3) + .5**(1/3)), places=2)  # piecewise-linear objective
        tu, xu = allocate(fields, owner, nominal, compute, limit, uniform=True)
        self.assertTrue(np.allclose(xu, [.5, .5]))
        self.assertGreater(t, tu)
        self.assertEqual(allocate(fields, owner, nominal, compute, 45. + np.array([15., 1.])), (None, None))
        self.assertEqual(allocate(fields, owner, nominal, compute, 45. + np.array([15., 1.]), uniform=True),
                         (None, None))
        self.assertGreaterEqual(X_MIN, 0.)

    def test_verdict_ignores_cases_without_a_feasible_comparison(self):
        self.assertEqual(verdict([.05, .04, .03, None]), 'worthwhile')
        self.assertEqual(verdict([.05, .04, .005, None]), 'uncertain')
        self.assertEqual(verdict([.005, None]), 'degenerate')
        # Review of 56f3af6: no comparable case is not evidence of a small loss.
        self.assertEqual(verdict([None, None]), 'no_data')
        # Only another layout is feasible: recorded as the full loss and counted.
        self.assertEqual(verdict([1., 1., 1.]), 'worthwhile')

    def test_rank_correlation_uses_average_ranks_and_rejects_constant_series(self):
        self.assertIsNone(rank_correlation([75., 65., 55.], [3., 3., 3.]))
        self.assertAlmostEqual(rank_correlation([75., 65., 55., 45.], [1., 2., 2., 4.]), 0.9486832980505138)
        self.assertEqual(rank_correlation([75., 65., 55.], [1., 2., 3.]), 1.)


if __name__ == '__main__':
    unittest.main()
