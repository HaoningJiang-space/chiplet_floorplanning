"""Controls for the research gate, FV budget and co-sizing baseline regressions found at af855d2."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import importlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from polygon_check import verdict as polygon_verdict  # noqa: E402
from superpose_check import verdict as superpose_verdict  # noqa: E402
from run_cosize import fixed_aspect  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement.cosize import cosize  # noqa: E402


def two_dies():
    return Problem('blind_control', ('a', 'b'), np.array([[6000., 6000.]]*2), np.array([100., 100.]),
                   (30000., 30000.), np.array([[0, 1]]), np.zeros((1, 2, 2)), limit_c=np.array([102., 102.]))


class ResearchGateTest(unittest.TestCase):
    def test_partial_samples_cannot_pass_frozen_seven_case_gates(self):
        polygon = json.loads((ROOT/'docs/evidence/polygon-check-v1.json').read_text())
        superposed = json.loads((ROOT/'docs/evidence/superposed-check-v1.json').read_text())
        self.assertEqual(polygon_verdict(polygon['cases']), ('adopt K=8', [8, 16]))
        self.assertEqual(superpose_verdict(superposed['cases'], superposed['rotation']), 'reject')
        for rows in ({}, {'Case1': polygon['cases']['Case1']}):
            self.assertEqual(polygon_verdict(rows), ('incomplete', []))
        self.assertEqual(superpose_verdict({}, dict(difference_error_k=0.)), 'incomplete')

    def test_reconstruction_mismatch_prevents_reuse_of_stored_fv_labels(self):
        polygon = json.loads((ROOT/'docs/evidence/polygon-check-v1.json').read_text())
        superposed = json.loads((ROOT/'docs/evidence/superposed-check-v1.json').read_text())
        for mismatch in (0.1, float('nan')):
            rows = deepcopy(polygon['cases'])
            rows['Case1']['euclid_reproduction_max_diff_k'] = mismatch
            self.assertEqual(polygon_verdict(rows), ('reproduction_mismatch', []))
        superposed['cases']['Case1']['euclid_reproduction_max_diff_k'] = 0.1
        self.assertEqual(superpose_verdict(superposed['cases'], superposed['rotation']), 'reproduction_mismatch')


class CosizeRegressionTest(unittest.TestCase):
    def test_failed_cheapest_option_does_not_skip_other_candidates_or_overrun_budget(self):
        module = importlib.import_module('chiplet_floorplanning.placement.cosize')
        p = two_dies()
        layout = Layout(np.array([[3000., 3000.], [9000., 3000.]]), np.zeros(2, int))
        proposals = [(10., 12., 6., 1, layout), (20., 18., 6., 2, layout)]
        results = [(None, (1., .006), 2), ((layout, -.5, .006), (-.5, .006), 1)]
        with patch.object(module, 'sized_milp', return_value=(proposals, {})), \
                patch.object(module, 'certify', side_effect=results) as certify:
            out = cosize(p, 0, .03, 3, thermal=False, rounds=1, steps=1)
        self.assertEqual(out['best']['cost_usd'], 20.)
        self.assertEqual(out['fv_solves'], 3)
        self.assertEqual([call.args[4] for call in certify.call_args_list], [1, 0])
        self.assertEqual([r['certified'] for r in out['history']], [False, True])

    def test_calibration_and_offset_cannot_overrun_small_fv_budgets(self):
        p = replace(two_dies(), power_w=np.ones(2))
        for budget in (0, 9, 10, 11, 12):
            out = cosize(p, 0, .03, budget, rounds=1, milp_s=2, steps=4, resolution=16, threads=1)
            self.assertLessEqual(out['fv_solves'], budget)
            if budget < 10:
                self.assertEqual(out['calibration_solves'], 0)

    def test_blind_search_polishes_on_the_trial_carrier_not_the_compact_extent(self):
        p = two_dies()
        # A real FV feasible point exists, while the old blind search stopped after its 12x6 mm box overheated.
        known = Layout(np.array([[6000., 15000.], [24000., 15000.]]), np.zeros(2, int))
        with Evaluator(p, 0, resolution=32) as evaluator:
            self.assertLess(evaluator.peaks_c([known])[0], 0)
        out = cosize(p, 0, .03, 100, thermal=False, rounds=3, milp_s=2, steps=4, resolution=32, threads=1)
        best = out['best']
        self.assertIsNotNone(best)
        self.assertLessEqual(out['fv_solves'], 100)
        sized = replace(p, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 0))
        self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, .03)
        with Evaluator(sized, 0, resolution=32) as evaluator:
            self.assertLessEqual(evaluator.peaks_c([layout])[0], 0)

    def test_fixed_aspect_keeps_the_same_winning_layout_and_joint_metrics(self):
        p = two_dies()
        centres = np.array([[[6000., 6000.], [24000., 6000.]], [[6000., 6000.], [18000., 6000.]]])
        rows = [dict(thermal=-2., length_m=.018), dict(thermal=-.5, length_m=.012)]
        archive = dict(centre_um=centres, rotation_deg=np.zeros((2, 2), int),
                       die_thermal=np.array([[-2., -3.], [-.5, -1.]]), solves=2)
        with patch('run_cosize.BISECTION_STEPS', 0), patch('run_cosize.run_front', return_value=(rows, archive)):
            out = fixed_aspect(p, 0, .015, 12, 2, 1., 1)
        best = out['best']
        self.assertEqual(best['layout_index'], 1)
        self.assertEqual(best['j_k'], -.5)
        self.assertEqual(best['length_m'], .012)
        np.testing.assert_array_equal(best['centre_um'], centres[1])
        self.assertEqual(best['rotation_deg'], [0, 0])
        self.assertEqual(best['die_overshoot_k'], [-.5, -1.])
        self.assertEqual(out['fv_solves'], 2)


if __name__ == '__main__':
    unittest.main()
