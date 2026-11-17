from dataclasses import replace
import unittest

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, Problem, is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.lp import legalize_relations, milp_relations
from chiplet_floorplanning.placement.thermal import die_peak_sensitivity


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

    def test_per_die_limits_make_every_thermal_quantity_an_overshoot(self):
        p = small_problem()
        layout = Layout(np.array([[6000., 6000.], [20000., 6000.], [8000., 25000.], [30000., 30000.]]), np.zeros(4, int))
        with Evaluator(p, 500, resolution=24) as plain:
            raw = plain.die_peaks_c([layout])[0]
        # Review of b50044e: two limit sets with the same spacing (95/85 vs 85/75) must give different scores;
        # an offset-only model reported both alike.
        scores = []
        for limits in (np.array([95., 85., 85., 90.]), np.array([85., 75., 75., 80.])):
            q = replace(p, limit_c=limits)
            with Evaluator(q, 500, resolution=24) as limited:
                np.testing.assert_allclose(limited.die_peaks_c([layout])[0], raw - limits)
                scores.append(limited.peaks_c([layout])[0])
                self.assertAlmostEqual(scores[-1], (raw - limits).max())
            peaks, _ = die_peak_sensitivity(q, layout, 500, 24)
            np.testing.assert_allclose(peaks, die_peak_sensitivity(p, layout, 500, 24)[0] - limits)
        self.assertAlmostEqual(scores[1] - scores[0], 10.0)
        case = dict(name='c', interposer_width_um=40000., interposer_height_um=40000., nets=[],
                    chiplets=[dict(name=n, width_um=w, height_um=h, power_w_decimal=1., limit_c=l)
                              for n, (w, h), l in zip('ab', p.size_um[:2], (95., 85.))])
        np.testing.assert_allclose(Problem.from_imported(case).limit_c, [95., 85.])
        case['chiplets'][1].pop('limit_c')
        with self.assertRaises(ValueError):
            Problem.from_imported(case)

if __name__ == '__main__':
    unittest.main()
