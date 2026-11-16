from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Problem, is_legal, pin_manhattan_um, sample_legal  # noqa: E402
from chiplet_floorplanning.placement.lp import TopologyLP, centre_relations, length_anneal, milp_relations  # noqa: E402
from chiplet_floorplanning.placement.search import length_descent  # noqa: E402


class RelationSpaceTest(unittest.TestCase):
    def setUp(self):
        self.problem = Problem.from_imported(synthetic_case(random.Random(5), chips=4, nets=80))
        self.length = lambda l: pin_manhattan_um(self.problem, l).sum()/1e6

    def test_milp_relations_finished_by_the_exact_lp_beat_greedy_descent(self):
        found = milp_relations(self.problem, 1000, time_limit_s=30)
        lp = TopologyLP(self.problem, found, 1000, pairs=0, relations=centre_relations(self.problem, found, 1000))
        exact = lp._layout(lp._solve(lp.length))
        self.assertTrue(is_legal(self.problem, exact, 1000))
        rng = np.random.default_rng(0)
        greedy = min(self.length(length_descent(self.problem, sample_legal(self.problem, 1000, rng), rng, 1000))
                     for _ in range(5))
        self.assertLessEqual(self.length(exact), greedy + 1e-9)

    def test_length_anneal_never_returns_a_longer_or_illegal_layout(self):
        start = sample_legal(self.problem, 1000, np.random.default_rng(1))
        best, length = length_anneal((self.problem, start, 1000, 0, 200, 0.02*self.length(start),
                                      0.0002*self.length(start)))
        self.assertTrue(is_legal(self.problem, best, 1000))
        self.assertAlmostEqual(length, self.length(best))
        self.assertLessEqual(length, self.length(start))


if __name__ == '__main__':
    unittest.main()
