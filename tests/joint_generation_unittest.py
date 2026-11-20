import unittest

import numpy as np

from chiplet_floorplanning.placement.geometry import is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.joint_generation import JointLandings
from chiplet_floorplanning.placement.problem import Layout, Problem


class JointLandingsTests(unittest.TestCase):
    def test_shared_links_and_joint_clearance_match_independent_cost_in_both_orders(self):
        p = Problem("links", ("a", "b", "c"), np.full((3, 2), 900.), np.array([2., 1., 2.]),
                    (6000., 5000.), np.array([[1, 0], [0, 1], [2, 0], [2, 2]]),
                    np.array([[[40., 30.], [0., 80.]], [[30., 100.], [0., 5.]],
                              [[-10., 60.], [25., 33.]], [[12., 0.], [20., 0.]]]))
        start = Layout(np.array([[1000., 1000.], [4000., 1000.], [2000., 3000.]]), np.array([90, 0, 180]))
        cap = pin_manhattan_um(p, start).sum() / 1e6
        pool = JointLandings(p, p, start, None, cap)
        for i in range(len(pool.xy)):
            partners, costs = pool.partners(i)
            found = dict(zip(partners, costs))
            for j in range(len(pool.xy)):
                if pool.chip[i] == pool.chip[j]:
                    continue
                layout = pool.move((i, j), 0.).apply(start)
                cost = pin_manhattan_um(p, layout).sum() / 1e6
                feasible = is_legal(p, layout, 100) and cost <= cap + 1e-9
                self.assertEqual(j in found, feasible)
                if feasible:
                    self.assertAlmostEqual(cost, found[j])
