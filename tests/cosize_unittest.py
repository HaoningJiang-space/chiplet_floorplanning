from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement import cosize as cosize_module  # noqa: E402
from chiplet_floorplanning.placement.cosize import anchored, cosize, family  # noqa: E402
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


class AnchoredTest(unittest.TestCase):
    def setUp(self):
        self.p = small_problem()
        self.anchor = Layout(np.array([[10., 10.], [30., 10.], [10., 30.], [30., 30.]])*1000, np.zeros(4, int))
        with Evaluator(self.p, 500, resolution=16) as evaluator:
            self.peak = evaluator.peaks_c([self.anchor])[0]
        self.length = pin_manhattan_um(self.p, self.anchor).sum()/1e6

    def test_designs_meet_the_anchor_limits_and_never_cost_more(self):
        limited = replace(self.p, limit_c=np.full(4, self.peak))
        for inner in ('proxy', 'axial', 'blind', 'relation_space'):
            out = anchored(limited, self.anchor, 500, self.length, 200, inner=inner, aspects=(1.0, 2.0),
                           size_s=10, threads=1, workers=1, resolution=16, chain_steps=3)
            self.assertLessEqual(abs(out['anchor']['j_k']), 1e-6)
            self.assertLessEqual(out['fv_solves'], 200)
            best = out['best']
            self.assertLessEqual(best['cost_usd'], interposer_cost(40., 40.)['total_usd'])
            sized = replace(limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
            layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
            self.assertTrue(is_legal(sized, layout, 500))
            with Evaluator(sized, 500, resolution=16) as evaluator:     # independent FV re-check
                self.assertLessEqual(evaluator.peaks_c([layout])[0], self.peak + 1e-6)
            self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, self.length + 1e-9)
            if inner == 'proxy':
                self.assertFalse(best['anchor'])        # the spread anchor leaves room to shrink

    def test_a_reference_that_does_not_reproduce_stops(self):
        limited = replace(self.p, limit_c=np.full(4, self.peak - 0.5))
        out = anchored(limited, self.anchor, 500, self.length, 200, workers=1, resolution=16)
        self.assertIsNone(out['best'])
        self.assertEqual(out['history'][0]['stop'], 'reproduction_mismatch')
        self.assertAlmostEqual(out['anchor']['j_k'], 0.5, places=6)    # measured, not assumed
        from run_cosize import fixed_aspect                            # the baseline uses the same check
        base = fixed_aspect(limited, 500, self.length, 100, 2, 5, 1, self.anchor, resolution=16)
        self.assertIsNone(base['best'])
        self.assertEqual(base['history'][0]['stop'], 'reproduction_mismatch')
        self.assertEqual(base['fv_solves'], 1)

    def test_zero_budget_spends_no_solve(self):
        limited = replace(self.p, limit_c=np.full(4, self.peak))
        for inner in ('blind', 'proxy'):
            out = anchored(limited, self.anchor, 500, self.length, 0, inner=inner, workers=1, resolution=16)
            self.assertEqual(out['fv_solves'], 0)
        out = anchored(limited, self.anchor, 500, self.length, 3, inner='proxy', workers=1, resolution=16)
        self.assertEqual(out['fv_solves'], 1)                          # anchor checked, calibration unaffordable
        self.assertEqual(out['history'][-1]['stop'], 'fv budget before calibration')

    def test_a_solver_timeout_keeps_the_mapped_start_and_the_family_goes_on(self):
        limited = replace(self.p, limit_c=np.full(4, self.peak))
        original = cosize_module.milp_relations

        def timeout(*args, **kwargs):
            cosize_module.MILP_STATUS['status'] = 'time_limit'
            return None
        cosize_module.milp_relations = timeout
        try:
            records, used = family((limited, self.anchor, 500, self.length, None, 1.0, 159.0, 1500.0, 100, 1.0, 1,
                                    None, 16, 3, cosize_module.CostParams(), 2, 1))
        finally:
            cosize_module.milp_relations = original
        trials = [r for r in records if 'status' in r]
        self.assertGreater(len(trials), 1)                             # a failure does not end the family
        self.assertTrue(any(r['certified'] and r['stages'][0]['stage'] == 'start' for r in trials))
        self.assertGreater(used, 0)


if __name__ == '__main__':
    unittest.main()
