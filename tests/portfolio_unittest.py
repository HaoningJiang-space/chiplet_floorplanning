from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement.portfolio import promote, successive_halving  # noqa: E402


class PromoteTest(unittest.TestCase):
    def test_round_zero_keeps_a_progressing_arm_of_every_mechanism_then_fills_by_cost(self):
        def arm(name, kind, cost, order):
            rec = [] if cost is None else [dict(certified=True, centre_um=[], cost_usd=cost)]
            return dict(name=name, kind=kind, records=rec, order=order)
        arms = [arm('joint', 'joint', None, 0), arm('r1', 'repair', 10.0, 1), arm('r2', 'repair', 11.0, 2),
                arm('r3', 'repair', 12.0, 3), arm('s1', 'rs', 50.0, 4), arm('s2', 'rs', None, 5)]
        self.assertEqual([a['name'] for a in promote(arms, 4, True)], ['r1', 's1', 'r2', 'r3'])
        self.assertEqual([a['name'] for a in promote(arms, 2, False)], ['r1', 'r2'])


class SuccessiveHalvingTest(unittest.TestCase):
    def test_the_best_design_is_certified_and_the_budget_holds(self):
        p = small_problem()
        anchor = Layout(np.array([[10., 10.], [30., 10.], [10., 30.], [30., 30.]])*1000, np.zeros(4, int))
        with Evaluator(p, 500, resolution=16) as evaluator:
            peak = evaluator.peaks_c([anchor])[0]
        limited = replace(p, limit_c=np.full(4, peak))
        length = pin_manhattan_um(p, anchor).sum()/1e6
        out = successive_halving(limited, anchor, 500, length, fv_budget=150, wall_s=120, threads=1, workers=1,
                                 resolution=16, chain_steps=3)
        self.assertLessEqual(out['fv_solves'], 150)
        best = out['best']
        sized = replace(limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 500))
        with Evaluator(sized, 500, resolution=16) as evaluator:          # independent FV re-check
            self.assertLessEqual(evaluator.peaks_c([layout])[0], 1e-6)
        self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, length + 1e-9)
        self.assertLess(best['cost_usd'], 208.75)                         # cheaper than the 40 x 40 anchor carrier

    def test_zero_budget_and_a_mismatched_anchor_stop(self):
        p = small_problem()
        anchor = Layout(np.array([[10., 10.], [30., 10.], [10., 30.], [30., 30.]])*1000, np.zeros(4, int))
        limited = replace(p, limit_c=np.full(4, 40.0))
        self.assertEqual(successive_halving(limited, anchor, 500, 1.0, fv_budget=0)['fv_solves'], 0)
        out = successive_halving(limited, anchor, 500, 1.0, fv_budget=10, resolution=16)
        self.assertEqual(out['history'][0]['stop'], 'reproduction_mismatch')


if __name__ == '__main__':
    unittest.main()
