from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem  # noqa: E402
from chiplet_floorplanning.placement.lp import ReachLP  # noqa: E402
from chiplet_floorplanning.placement.search import length_descent  # noqa: E402
from reach_cost import excess_mm, link_gaps_mm, link_pairs  # noqa: E402


class ReachCostTest(unittest.TestCase):
    def setUp(self):
        self.problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        self.pairs, self.lanes = link_pairs(self.problem)

    def test_link_gap_is_the_rectangle_gap(self):
        self.assertEqual(self.pairs.tolist(), [[0, 1]])
        self.assertEqual(self.lanes.tolist(), [self.problem.pin_chip.shape[0]])
        w0 = self.problem.size_um[0, 0]
        w1 = self.problem.size_um[1, 0]
        apart = Layout(np.array([[2000., 1000.], [2000. + (w0 + w1)/2 + 1500., 1000.]]), np.array([0, 0]))
        np.testing.assert_allclose(link_gaps_mm(self.problem, apart, self.pairs), [1.5])
        touching = Layout(np.array([[2000., 1000.], [2000. + (w0 + w1)/2, 1000.]]), np.array([0, 0]))
        np.testing.assert_allclose(link_gaps_mm(self.problem, touching, self.pairs), [0.])
        self.assertAlmostEqual(excess_mm(self.problem, apart, self.pairs, 1.0), .5)
        self.assertEqual(excess_mm(self.problem, apart, self.pairs, 2.0), 0.)

    def test_evaluator_and_descent_use_the_given_interconnect_cost(self):
        longest = lambda l: link_gaps_mm(self.problem, l, self.pairs).max()
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        self.assertEqual(Evaluator(self.problem, 0., interconnect=longest).length_m(layout), longest(layout))
        descended = length_descent(self.problem, layout, np.random.default_rng(0), 0., grid_um=100, cost=longest)
        self.assertLessEqual(longest(descended), longest(layout))

    def test_reach_lp_pulls_linked_dies_within_reach(self):
        w0, w1 = self.problem.size_um[:, 0]
        apart = Layout(np.array([[w0/2, 1000.], [w0 + w1/2 + 3000., 1000.]]), np.array([0, 0]))
        self.assertAlmostEqual(link_gaps_mm(self.problem, apart, self.pairs)[0], 3.0)
        over, fitted = ReachLP(self.problem, apart, 0., self.pairs, 1.0).fit()
        self.assertEqual(over, 0.0)
        self.assertLessEqual(link_gaps_mm(self.problem, fitted, self.pairs).max(), 1.0)
        swept = ReachLP(self.problem, apart, 0., self.pairs, 1.0).sweep(3)
        self.assertTrue(swept)
        self.assertTrue(all(link_gaps_mm(self.problem, l, self.pairs).max() <= 1.0 for l in swept))


if __name__ == '__main__':
    unittest.main()
