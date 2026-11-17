from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement.cosize import cosize  # noqa: E402
from chiplet_floorplanning.placement.cost import interposer_cost, max_height  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from chiplet_floorplanning.placement.lp import legalize_relations, milp_relations, pin_length_cut  # noqa: E402


class CostFieldTest(unittest.TestCase):
    def test_max_height_follows_the_exposure_fields(self):
        self.assertAlmostEqual(max_height(20.0, 1, 50.0), 33.0)
        self.assertAlmostEqual(max_height(30.0, 1, 50.0), 26.0)      # turned field: 33 wide, 26 high
        self.assertAlmostEqual(max_height(20.0, 2, 80.0), 66.0)
        self.assertEqual(max_height(20.0, 1, 10.0), 10.0)


class MinAreaMilpTest(unittest.TestCase):
    def test_min_area_matches_the_smallest_level_by_brute_force(self):
        p = small_problem()
        levels = np.array([12., 14., 16., 18., 20.])
        layout, (w, h), level = milp_relations(p, 500, 30, sizing=(levels, None, [], None, True))
        area = w*h
        best = np.inf
        for k, v in enumerate(levels):   # per level: smallest area with the width fixed to v
            out = milp_relations(p, 500, 30, sizing=(levels, None, [l for l in range(5) if l != k], None, True))
            if out is not None:
                best = min(best, levels[out[2]]*out[1][1])
        self.assertLessEqual(area, best + 1e-3)
        self.assertLessEqual(w, levels[level] + 1e-6)

    def test_aspect_floor_holds_for_the_box(self):
        p = small_problem()
        levels = np.array([12., 16., 20., 24., 28.])
        _, (w, h), level = milp_relations(p, 500, 30, sizing=(levels, None, [], None, True, levels/1.2))
        free = milp_relations(p, 500, 30, sizing=(levels, None, [], None, True))
        # The floored box cannot be smaller than the free optimum, and its extent fits inside the chosen level.
        self.assertGreaterEqual(levels[level]*max(h, levels[level]/1.2) + 1e-3, levels[free[2]]*free[1][1])
        self.assertLessEqual(w, levels[level] + 1e-6)


def opposed_pins():
    """docs/proxy-budget-review.md section 3: two 6 x 6 mm dies, four nets with opposite offsets, so the clustered
    length cancels the offsets and understates the exact per-pin length."""
    offsets = np.array([[[0., 2500.], [0., -2500.]], [[0., -2500.], [0., 2500.]],
                        [[0., 2500.], [0., -2500.]], [[0., -2500.], [0., 2500.]]])
    return Problem('opposed', ('a', 'b'), np.array([[6000., 6000.]]*2), np.array([1., 1.]), (40000., 40000.),
                   np.array([[0, 1]]*4), offsets)


class PinCutTest(unittest.TestCase):
    def test_cut_is_tight_at_its_layout_and_a_minorant_elsewhere(self):
        p = opposed_pins()
        n = p.count
        ix, iy, iz = 0, n, 2*n
        rng = np.random.default_rng(0)
        for _ in range(5):
            at = Layout(rng.uniform(3000, 37000, (2, 2)), rng.integers(0, 4, 2)*90)
            entries, constant = pin_length_cut(p, at, ix, iy, iz)
            for other in (at, Layout(rng.uniform(3000, 37000, (2, 2)), rng.integers(0, 4, 2)*90)):
                x = np.zeros(iz + 4*n)
                x[ix:ix + n], x[iy:iy + n] = other.centre_um[:, 0]/1000, other.centre_um[:, 1]/1000
                x[iz + 4*np.arange(n) + (other.rotation_deg//90) % 4] = 1
                value = sum(v*x[k] for k, v in entries) + constant
                exact = pin_manhattan_um(p, other).sum()/1000
                if other is at:
                    self.assertAlmostEqual(value, exact, places=6)
                else:
                    self.assertLessEqual(value, exact + 1e-6)

    def test_cuts_bring_the_milp_within_the_exact_budget(self):
        p = opposed_pins()
        budget = 28.0
        raw = milp_relations(p, 0, 10, wire_mm=budget)
        self.assertGreater(pin_manhattan_um(p, raw).sum()/1000, budget)       # the relaxation alone fails
        cuts = []
        for _ in range(10):
            out = milp_relations(p, 0, 10, wire_mm=budget, wire_cuts=cuts)
            if out is None or pin_manhattan_um(p, out).sum()/1000 <= budget + 1e-6:
                break
            cuts.append(out)
        self.assertIsNotNone(out)
        self.assertLessEqual(pin_manhattan_um(p, out).sum()/1000, budget + 1e-6)


class CosizeTest(unittest.TestCase):
    def test_certified_design_is_legal_within_limits_and_budget(self):
        p = small_problem()
        start = legalize_relations(p, milp_relations(p, 500, 10), 500)
        with Evaluator(p, 500, resolution=16) as evaluator:
            peak = evaluator.peaks_c([start])[0]
        limited = replace(p, limit_c=np.full(4, peak + 3.0))
        budget = pin_manhattan_um(p, start).sum()/1e6*1.5
        out = cosize(limited, 500, budget, 120, rounds=4, milp_s=10, steps=3, resolution=16)
        self.assertLessEqual(out['fv_solves'], 120)
        best = out['best']
        self.assertIsNotNone(best)
        self.assertLessEqual(best['j_k'], 0)
        self.assertLessEqual(best['length_m'], budget + 1e-9)
        sized = replace(limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        from chiplet_floorplanning.placement import Layout
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 500))
        self.assertLess(best['cost_usd'], interposer_cost(40., 40.)['total_usd'])
        polygon = cosize(limited, 500, budget, 120, rounds=4, milp_s=10, steps=3, resolution=16, directions=8)
        self.assertIsNotNone(polygon['best'])
        self.assertLessEqual(polygon['best']['j_k'], 0)
        self.assertLessEqual(polygon['fv_solves'], 120)
        blind = cosize(limited, 500, budget, 120, thermal=False, rounds=4, milp_s=10, steps=3, resolution=16)
        self.assertEqual(blind['calibration_solves'], 0)


if __name__ == '__main__':
    unittest.main()
