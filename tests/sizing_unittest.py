from dataclasses import replace
import unittest

import numpy as np

from chiplet_floorplanning.placement import Problem, is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.lp import legalize_relations, milp_relations


def small_problem():
    # Four dies; nets of a pair share their pins (centres), so the MILP's clustered length is the exact length.
    pins = np.array([[0, 1]]*8 + [[1, 2]]*5 + [[2, 3]]*7 + [[0, 3]]*2 + [[0, 2]]*3)
    return Problem('small', tuple('abcd'), np.array([[8000., 6000.], [6000., 6000.], [10000., 4000.], [5000., 7000.]]),
                   np.array([30., 10., 20., 5.]), (40000., 40000.), pins, np.zeros((len(pins), 2, 2)))


class SizingMilpTest(unittest.TestCase):
    def test_sized_milp_equals_the_best_fixed_carrier_over_width_levels(self):
        p = small_problem()
        levels, cap, gap = [12., 16., 20., 24., 28.], 360., 500
        layout, (width, height), level = milp_relations(p, gap, 30, sizing=(levels, cap, []))
        self.assertLessEqual(width, levels[level] + 1e-6)
        self.assertLessEqual(width*height, cap + 1e-3)
        length = pin_manhattan_um(p, layout).sum()
        best = np.inf
        for w in levels:          # brute force: each width level with its largest allowed height
            fixed = replace(p, carrier_um=(w*1000, min(40.0, cap/w)*1000))
            found = milp_relations(fixed, gap, 30)
            if found is not None:
                best = min(best, pin_manhattan_um(fixed, found).sum())
        self.assertAlmostEqual(length, best, delta=1e-2)
        sized = replace(p, carrier_um=(width*1000, height*1000))
        legal = legalize_relations(sized, layout, gap)
        self.assertTrue(legal is not None and is_legal(sized, legal, gap))

    def test_excluded_widths_are_not_chosen_and_an_impossible_cap_is_none(self):
        p = small_problem()
        levels = [12., 16., 20., 24., 28.]
        _, _, first = milp_relations(p, 500, 30, sizing=(levels, 360., []))
        _, (width, _), second = milp_relations(p, 500, 30, sizing=(levels, 360., [first]))
        self.assertNotEqual(first, second)
        self.assertLessEqual(width, levels[second] + 1e-6)
        self.assertIsNone(milp_relations(p, 500, 30, sizing=(levels, 100., [])))   # the dies alone need ~200 mm^2


if __name__ == '__main__':
    unittest.main()
