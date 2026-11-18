from dataclasses import replace
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement import schedule  # noqa: E402


class ChainTest(unittest.TestCase):
    def setUp(self):
        from chiplet_floorplanning.placement import Problem
        # three 10 x 6 mm dies in a row, 1 mm gaps: the row needs 32 mm of width and 6 mm of height
        pins = np.array([[0, 1], [1, 2]])
        self.p = Problem('row', ('a', 'b', 'c'), np.array([[10000., 6000.]]*3), np.array([10., 10., 10.]),
                         (40000., 40000.), pins, np.zeros((2, 2, 2)))
        self.row = Layout(np.array([[6000., 20000.], [17000., 20000.], [28000., 20000.]]), np.zeros(3, int))

    def test_the_longest_chain_is_the_minimum_extent(self):
        from chiplet_floorplanning.placement.lp import centre_relations
        (w, h), chains = schedule.min_extent(self.p, self.row, centre_relations(self.p, self.row, 1000), 1000)
        self.assertAlmostEqual(w, 32.0)
        self.assertAlmostEqual(h, 6.0)
        self.assertEqual(chains[0], [0, 1, 2])

    def test_flipping_the_binding_chain_fits_a_narrower_carrier(self):
        sized = replace(self.p, carrier_um=(22000., 14000.))        # too narrow for the row, tall enough for two rows
        self.assertIsNone(schedule.fit_into(sized, self.row, self.p.carrier_um, 1000))
        layout, flips = schedule.chain_flip(sized, self.row, 1000)
        self.assertIsNotNone(layout)
        self.assertGreaterEqual(flips, 1)
        self.assertTrue(is_legal(sized, layout, 1000))


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.p = small_problem()
        self.anchor = Layout(np.array([[10., 10.], [30., 10.], [10., 30.], [30., 30.]])*1000, np.zeros(4, int))
        with Evaluator(self.p, 500, resolution=16) as evaluator:
            self.peak = evaluator.peaks_c([self.anchor])[0]
        self.limited = replace(self.p, limit_c=np.full(4, self.peak))
        self.length = pin_manhattan_um(self.p, self.anchor).sum()/1e6

    def test_the_best_design_is_certified_within_budget(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() + 300, threads=1, workers=1, resolution=16, chain_steps=3)
        self.assertLessEqual(out['fv_solves'], 200)
        best = out['best']
        sized = replace(self.limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 500))
        with Evaluator(sized, 500, resolution=16) as evaluator:          # independent FV re-check
            self.assertLessEqual(evaluator.peaks_c([layout])[0], 1e-6)
        self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, self.length + 1e-9)
        self.assertLess(best['cost_usd'], 208.75)
        targets = [r for r in out['history'] if 'stages' in r]
        self.assertTrue(targets and all('first_certifier' in r and 'fv_total' in r for r in targets))

    def test_v8_designs_are_certified_within_budget(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() + 300, threads=1, workers=1, resolution=16, chain_steps=3,
                                 v8=True)
        self.assertEqual(out['inner'], 'v8')
        self.assertLessEqual(out['fv_solves'], 200)
        best = out['best']
        sized = replace(self.limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 500))
        with Evaluator(sized, 500, resolution=16) as evaluator:
            self.assertLessEqual(evaluator.peaks_c([layout])[0], 1e-6)
        self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, self.length + 1e-9)

    def test_nothing_starts_after_the_shared_deadline(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() - 1, resolution=16)
        self.assertEqual(out['fv_solves'], 0)
        from run_cosize import fixed_aspect                            # the baseline takes the same deadline
        with patch('run_cosize.relation_front') as search:
            base = fixed_aspect(self.limited, 500, self.length, 100, 2, 5, 1, self.anchor, resolution=16,
                                deadline=time.perf_counter() - 1)
        search.assert_not_called()
        self.assertEqual(base['history'][-1]['stop'], 'deadline')

    def test_a_solver_status_other_than_infeasible_is_no_proof(self):
        from chiplet_floorplanning.placement import cosize
        def other(*args, **kwargs):
            cosize.MILP_STATUS['status'] = 'highs_4'          # scipy.optimize.milp status 4: "other", not infeasible
            return None
        with patch.object(cosize, 'milp_relations', side_effect=other):
            _, _, proof, _ = cosize.fixed_carrier(self.limited, 500, self.length, None, None, 5.0, 1, None)
        self.assertIsNone(proof)

    def test_a_larger_late_success_does_not_replace_a_smaller_parent(self):
        results = iter([True, True])                            # first target certifies, then a stale larger one
        seen = []

        def fake(ctx, shape, area, deadline):
            seen.append((area, shape['base_um']))
            ok = next(results, False)
            w, h = schedule.box(area, shape['aspect'])
            rec = dict(stages=[], certified=bool(ok), first_certifier='move' if ok else None, width_mm=w, height_mm=h,
                       cost_usd=area)
            return rec, ((self.anchor, -1.0, 0.1) if ok else None)
        with patch.object(schedule, 'cascade', side_effect=fake), patch.object(schedule, 'SHAPES', ()):
            schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=50,
                               deadline=time.perf_counter() + 60, threads=1, workers=1, resolution=16)
        first_area = seen[0][0]
        self.assertTrue(all(area < first_area for area, _ in seen[1:]))   # no stale target above it was tried

    def test_no_repair_starts_after_the_deadline(self):
        from chiplet_floorplanning.placement import cosize
        late = time.perf_counter() + 0.5

        def slow_milp(*args, **kwargs):
            time.sleep(1.0)                                    # returns after the deadline
            return self.anchor, ['optimal'], None, 1.0
        shape = dict(aspect=1.0, base=self.anchor, base_um=(1000., 1000.), rng=np.random.default_rng(0))
        ctx = dict(problem=self.limited, gap_um=500, length_m=self.length, params=schedule.CostParams(), fv=0,
                   fv_budget=100, resolution=16, threads=1, workers=1, v8=True, started=time.perf_counter())
        with patch.object(cosize, 'fixed_carrier', side_effect=slow_milp), \
                patch.object(schedule, 'fit_into', return_value=None), \
                patch.object(schedule, 'chain_flip', return_value=(None, 0)), \
                patch.object(schedule, 'certify', side_effect=AssertionError('certify after the deadline')):
            rec, ok = schedule.cascade(ctx, shape, 1600.0, late)
        self.assertIsNone(ok)
        self.assertIsNone(rec['first_certifier'])

    def test_an_ordinary_failure_is_not_a_proof(self):
        calls = []

        def fail(ctx, shape, area, deadline):
            calls.append(area)
            return dict(stages=[], certified=False, first_certifier=None, width_mm=1, height_mm=1), None
        with patch.object(schedule, 'cascade', side_effect=fail):
            schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                               deadline=time.perf_counter() + 60, threads=1, workers=1, resolution=16)
        first = calls[0]
        self.assertTrue(any(a < first for a in calls))                 # the lower half is still tried
        self.assertTrue(any(a > first for a in calls))                 # and towards the certified side first


if __name__ == '__main__':
    unittest.main()
