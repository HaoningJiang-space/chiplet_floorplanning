from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement import cosize as cosize_module  # noqa: E402
from chiplet_floorplanning.placement.cosize import anchored, family  # noqa: E402
from chiplet_floorplanning.placement.cost import interposer_cost  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from chiplet_floorplanning.placement.lp import milp_relations, pin_length_cut  # noqa: E402


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


class CandidateRetentionTest(unittest.TestCase):
    def test_a_within_budget_axial_solution_survives_an_over_budget_polygon(self):
        # Review 08c5ec7: same geometry, the second die turned 180 degrees; clustered 24 mm, exact 24 vs 44 mm.
        from chiplet_floorplanning.placement.cosize import fixed_carrier
        p = opposed_pins()
        pair = [Layout(np.array([[10000., 20000.], [30000., 20000.]]), np.array([0, r])) for r in (0, 180)]
        good, bad = sorted(pair, key=lambda l: pin_manhattan_um(p, l).sum())
        lengths = [pin_manhattan_um(p, l).sum()/1000 for l in (good, bad)]
        self.assertGreater(lengths[1], lengths[0])
        budget = (min(lengths) + max(lengths))/2/1000
        calls = []

        def fake(problem, gap_um, time_s, **kwargs):
            calls.append(kwargs.get('directions'))
            cosize_module.MILP_STATUS['status'] = 'time_limit'
            return good if kwargs.get('directions') is None else bad
        original = cosize_module.milp_relations
        cosize_module.milp_relations = fake
        try:
            out, statuses, proof, _ = fixed_carrier(p, 0, budget, 'model', None, 100.0, 1, 8)
        finally:
            cosize_module.milp_relations = original
        self.assertIs(out, good)
        self.assertIsNone(proof)
        self.assertEqual(calls, [None, 8])


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

    def test_an_illegal_anchor_stops_all_three_drivers_before_the_first_fv(self):
        from unittest.mock import patch
        from run_cosize import fixed_aspect
        from chiplet_floorplanning.placement.schedule import scheduled
        limited = replace(self.p, limit_c=np.full(4, self.peak))
        with patch.object(cosize_module, 'slp_chain', side_effect=AssertionError('illegal anchor reached FV')):
            runs = [scheduled(limited, self.anchor, 30000, self.length, 10),
                    anchored(limited, self.anchor, 30000, self.length, 10),
                    fixed_aspect(limited, 30000, self.length, 10, 2, 5, 1, self.anchor)]
        for out in runs:
            self.assertIsNone(out['best'])
            self.assertEqual(out['fv_solves'], 0)
            self.assertFalse(out['anchor']['ok'])
            self.assertTrue(out['anchor']['violations']['pairs'])
            self.assertIsNone(out['anchor']['j_k'])

    def test_the_baseline_accepts_an_anchor_within_the_reproduction_tolerance(self):
        from unittest.mock import patch
        from run_cosize import fixed_aspect
        limited = replace(self.p, limit_c=np.full(4, self.peak - 1e-9))          # J = +1e-9 K, inside 1e-6 K
        with patch('run_cosize.BISECTION_STEPS', 0):
            out = fixed_aspect(limited, 500, self.length, 10, 2, 5, 1, self.anchor, resolution=16)
        self.assertTrue(out['history'][0]['certified'])
        self.assertEqual(out['best']['width_mm'], 40.0)

    def test_an_anchor_below_a_relaxed_limit_reproduces_with_the_expected_slack(self):
        limited = replace(self.p, limit_c=np.full(4, self.peak + 1.0))
        out = anchored(limited, self.anchor, 500, self.length, 0 + 1, inner='blind', workers=1, resolution=16,
                       expected_j_k=-1.0)
        self.assertTrue(out['anchor']['ok'])
        self.assertAlmostEqual(out['anchor']['j_k'], -1.0, places=6)
        out = anchored(limited, self.anchor, 500, self.length, 1, inner='blind', workers=1, resolution=16)
        self.assertEqual(out['history'][0]['stop'], 'reproduction_mismatch')
        hot = replace(self.p, limit_c=np.full(4, self.peak - 1.0))      # reproduces J = +1 but overshoots
        out = anchored(hot, self.anchor, 500, self.length, 1, inner='blind', workers=1, resolution=16,
                       expected_j_k=1.0)
        self.assertEqual(out['history'][0]['stop'], 'reproduction_mismatch')

    def test_execution_errors_are_not_mistaken_for_a_missing_start(self):
        from unittest.mock import patch
        from chiplet_floorplanning.placement.cosize import try_carrier
        limited = replace(self.p, limit_c=np.full(4, self.peak - 5.0))   # the mapped start fails: the search runs
        with patch('chiplet_floorplanning.placement.methods.relation_front', side_effect=RuntimeError('solver died')):
            with self.assertRaises(RuntimeError):
                try_carrier(limited, self.anchor, limited.carrier_um, 500, self.length, 'relation_space', 0 + 50, 5.0,
                            1, None, 16, 0, 2, 1, rs_share=20)

    def test_a_small_relation_space_share_still_searches(self):
        from unittest.mock import patch
        from chiplet_floorplanning.placement import methods
        seen = {}
        original = methods.METHODS['relation_space']

        def spy(run, starts, rng, **kwargs):
            seen['starts'] = len(starts)
            return original(run, starts, rng, **kwargs)
        with patch.dict(methods.METHODS, relation_space=spy):
            methods.relation_front(self.p, 500, 20, 2, [self.anchor], dict(milp_s=5, workers=1))
        self.assertLessEqual(seen['starts'], 1 + 2*(20//6))      # the anchor plus 3 random and 3 descent starts

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
