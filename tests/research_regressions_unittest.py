"""Control for the co-sizing baseline regression found at af855d2 (the other controls of that review covered code
removed after 33ad191: the joint sizing MILP and the superposition/polygon check tools)."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from run_cosize import fixed_aspect  # noqa: E402
from chiplet_floorplanning.placement import Problem  # noqa: E402


def two_dies():
    return Problem('blind_control', ('a', 'b'), np.array([[6000., 6000.]]*2), np.array([100., 100.]),
                   (30000., 30000.), np.array([[0, 1]]), np.zeros((1, 2, 2)), limit_c=np.array([102., 102.]))


class FixedAspectRegressionTest(unittest.TestCase):
    def test_fixed_aspect_keeps_the_same_winning_layout_and_joint_metrics(self):
        p = two_dies()
        centres = np.array([[[6000., 6000.], [24000., 6000.]], [[6000., 6000.], [18000., 6000.]]])
        rows = [dict(thermal=-2., length_m=.018), dict(thermal=-.5, length_m=.012)]
        archive = dict(centre_um=centres, rotation_deg=np.zeros((2, 2), int),
                       die_thermal=np.array([[-2., -3.], [-.5, -1.]]), solves=2)
        with patch('run_cosize.BISECTION_STEPS', 0), patch('run_cosize.relation_front', return_value=(rows, archive)):
            out = fixed_aspect(p, 0, .015, 12, 2, 1., 1)
        best = out['best']
        self.assertEqual(best['layout_index'], 1)
        self.assertEqual(best['j_k'], -.5)
        self.assertEqual(best['length_m'], .012)
        np.testing.assert_array_equal(best['centre_um'], centres[1])
        self.assertEqual(best['rotation_deg'], [0, 0])
        self.assertEqual(best['die_overshoot_k'], [-.5, -1.])
        self.assertEqual(out['fv_solves'], 2)

    def test_a_checked_anchor_stands_when_the_budget_cannot_fund_a_search(self):
        from chiplet_floorplanning.placement import Evaluator, Layout
        from chiplet_floorplanning.placement.geometry import pin_manhattan_um
        p = replace(two_dies(), limit_c=None)
        anchor = Layout(np.array([[6000., 6000.], [24000., 6000.]]), np.zeros(2, int))
        with Evaluator(p, 0, resolution=16) as evaluator:
            peak = evaluator.peaks_c([anchor])[0]
        limited = replace(p, limit_c=np.array([peak, peak]))
        out = fixed_aspect(limited, 0, pin_manhattan_um(p, anchor).sum()/1e6, 3, 2, 1., 1, anchor, resolution=16)
        self.assertEqual(out['fv_solves'], 1)
        self.assertTrue(out['best']['anchor'])


if __name__ == '__main__':
    unittest.main()
