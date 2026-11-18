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

    def test_tight_crop_preserves_pins_and_clamps_the_translation_at_the_edge(self):
        from chiplet_floorplanning.placement.cosize import tight_crop
        sized, moved = tight_crop(self.p, self.row)
        self.assertEqual(sized.carrier_um, (32000, 10700))
        np.testing.assert_array_equal(moved.centre_um, self.row.centre_um + [-1000., -14650.])
        np.testing.assert_array_equal(pin_manhattan_um(sized, moved), pin_manhattan_um(self.p, self.row))
        self.assertTrue(is_legal(sized, moved, 1000))

    def test_wire_seed_is_certified_before_annealing_and_reuses_the_parent_solve(self):
        from chiplet_floorplanning.placement import methods
        from chiplet_floorplanning.placement.cosize import WireSeedCheck
        p = replace(self.p, limit_c=np.full(3, 250.))
        for limit, late in ((2, False), (3, False), (3, True)):
            now = [0.]
            check = WireSeedCheck(1., float('inf'), 7, 0., 10.)
            def anneal(job):
                self.assertEqual([e['status'] for e in check.records], ['certified', 'certified'])
                now[0] = 11. if late else 1.
                return job[1], 0.
            def resume(run, starts, rng, **opts):
                run.evaluate(starts)
                self.assertEqual(run.evaluator.solves, 2)
            with Evaluator(p, 1000, resolution=16) as ev, patch('time.perf_counter', side_effect=lambda: now[0]), \
                    patch.object(methods, 'milp_relations', return_value=self.row), \
                    patch.object(methods, 'length_anneal', side_effect=anneal) as chains, \
                    patch.object(methods, 'topology_slp', side_effect=resume) as search:
                run = methods.Run(ev, limit)
                methods.relation_space(run, [], np.random.default_rng(2), chains=1, seed_check=check)
                self.assertEqual(check.solves, ev.solves)
                self.assertEqual([e['fv_total'] for e in check.records], [8, 9])
                self.assertEqual(chains.call_count, int(limit > 2))
                self.assertEqual(search.call_count, int(limit > 2 and not late))

    def test_seed_rejects_uncompetitive_or_long_wire_layouts_without_spending_fv(self):
        from chiplet_floorplanning.placement import methods
        from chiplet_floorplanning.placement.cosize import WireSeedCheck
        for length, cap, status in ((0., float('inf'), 'wire'), (1., 0., 'price')):
            with Evaluator(self.p, 1000, resolution=16) as ev:
                check = WireSeedCheck(length, cap, 0, 0., float('inf'))
                self.assertTrue(check.evaluate(methods.Run(ev, 3), self.row))
                self.assertEqual((check.records[0]['status'], ev.solves), (status, 0))

    def test_finishing_fv_is_charged_and_only_an_in_time_certificate_replaces_the_parent(self):
        from chiplet_floorplanning.placement import cosize
        p = replace(self.p, limit_c=np.full(3, 250.))
        length = pin_manhattan_um(p, self.row).sum()/1e6
        parent = dict(width_mm=40., height_mm=40., centre_um=self.row.centre_um.tolist(),
                      rotation_deg=self.row.rotation_deg.tolist(), arm='repair')
        for budget, clock, status, used in ((1, [0.], 'fv_budget', 1), (2, [2.], 'deadline', 1),
                                             (2, [0., 0., 2.], 'deadline', 2), (2, [0., 0., 0.], 'certified', 2)):
            result = dict(history=[], anchor=dict(ok=True), best=parent, fv_solves=1)
            with patch.object(cosize.time, 'perf_counter', side_effect=clock):
                cosize.finish_crop(p, self.row, 1000, length, result, budget, 1., resolution=16)
            self.assertEqual(result['history'][-1]['status'], status)
            self.assertEqual(result['fv_solves'], used)
            if status == 'certified':
                self.assertEqual(result['best']['arm'], 'tight_crop')
            else:
                self.assertIs(result['best'], parent)

    def test_only_global_improvements_spend_a_crop_solve(self):
        from chiplet_floorplanning.placement.cosize import crop_candidate
        p = replace(self.p, limit_c=np.full(3, 250.))
        cropped_price = schedule.interposer_cost(32., 10.7)['total_usd']
        for cap, used, status in ((cropped_price, 0, 'no_cheaper_crop'), (cropped_price + 1., 1, 'certified')):
            rec = crop_candidate(p, self.row, 1000, 1., 'repair', -1., cap, 5, 6, float('inf'), 16)
            self.assertLess(cap, rec['parent_cost_usd'])    # the search would discard this parent on price alone
            self.assertEqual((rec['fv_solves'], rec['status']), (used, status))

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

    def test_span_query_charges_internal_pins_and_the_gap(self):
        pins = np.vstack((self.p.pin_chip, [1, 1]))
        offsets = np.zeros((3, 2, 2))
        offsets[2, 1] = [600., 400.]             # 1 mm on die b, unchanged by translation
        lp = schedule.TopologyLP(replace(self.p, pin_chip=pins, pin_offset_um=offsets), self.row, 1000, pairs=0)
        self.assertIsNone(lp.minimum_span_mm(0, 0.0229))
        self.assertAlmostEqual(lp.minimum_span_mm(0, 0.023), 32.0)
        self.assertAlmostEqual(lp.minimum_span_mm(1, 0.023), 6.0)

    def test_rectangle_query_skips_only_axes_already_at_the_geometric_floor(self):
        parent = replace(self.p, carrier_um=(32000., 40000.))
        row = replace(self.row, centre_um=self.row.centre_um - [1000., 0.])
        ctx = dict(gap_um=1000, length_m=1., fv=0, fv_budget=10)
        with patch.object(schedule.TopologyLP, 'minimum_span_mm', return_value=None) as solve:
            schedule.refine_rectangle(ctx, parent, row, float('inf'), float('inf'))
        solve.assert_called_once_with(1, 1.)
        elongated = replace(parent, carrier_um=(40000., 120000.))
        with patch.object(schedule.TopologyLP, 'minimum_span_mm', return_value=None) as solve:
            schedule.refine_rectangle(ctx, elongated, row, float('inf'), float('inf'))
        solve.assert_called_once_with(1, 1.)   # geometry allows a narrower row, the 3:1 shape limit does not
        tight = replace(parent, carrier_um=(32000., 6000.))
        row = replace(row, centre_um=row.centre_um - [0., 17000.])
        with patch.object(schedule, 'TopologyLP', side_effect=AssertionError('both sides at floor')):
            self.assertEqual(schedule.refine_rectangle(ctx, tight, row, float('inf'), float('inf')), [])

    def test_rigid_move_certifies_a_smaller_carrier_without_scaling_the_layout(self):
        parent = replace(self.row, centre_um=self.row.centre_um + [2000., 0.])
        p = replace(self.p, limit_c=np.full(3, 300.))
        length = pin_manhattan_um(p, parent).sum()/1e6
        ctx = dict(problem=p, fv=0, fv_budget=2, gap_um=1000, length_m=length, params=schedule.CostParams(),
                   resolution=16, started=time.perf_counter(), rectangles=True)
        shape = dict(base=parent, base_um=p.carrier_um, aspect=1.)
        rec, ok = schedule.cascade(ctx, shape, 36.**2, time.perf_counter() + 60)
        self.assertEqual((rec['first_certifier'], ctx['fv']), ('move', 1))
        np.testing.assert_allclose(ok[0].centre_um, parent.centre_um - 2000)


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
        self.assertEqual(out['inner'], 'rectangles')
        self.assertTrue(any(r.get('arm') == 'rectangle_lp' for r in out['history']))
        targets = [r for r in out['history'] if 'stages' in r]
        self.assertTrue(targets and all('first_certifier' in r and 'fv_total' in r for r in targets))

    def test_both_searches_spend_the_last_available_solve_on_a_new_parent(self):
        from run_cosize import fixed_aspect
        p = replace(self.limited, limit_c=self.limited.limit_c + 20.)
        opts = dict(online_crop=True, expected_j_k=-20., resolution=16)
        for out in (schedule.scheduled(p, self.anchor, 500, self.length, fv_budget=2, **opts),
                    fixed_aspect(p, 500, self.length, 2, 2, 1, 1, self.anchor, **opts)):
            self.assertEqual(out['fv_solves'], 2)
            crop, = [r for r in out['history'] if r.get('arm') == 'tight_crop']
            self.assertEqual((crop['parent_arm'], crop['fv_total'], crop['status']), ('anchor', 2, 'certified'))
            self.assertEqual(out['best']['cost_usd'], crop['cost_usd'])

    def test_v8_designs_are_certified_within_budget(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() + 300, threads=1, workers=1, resolution=16, chain_steps=3,
                                 v8=True)
        self.assertEqual(out['inner'], 'v8')
        self.assertFalse(any(r.get('arm') == 'rectangle_lp' for r in out['history']))
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

    def test_baseline_skips_search_if_mapping_uses_the_remaining_time(self):
        from run_cosize import fixed_aspect
        now = [0.]

        def slow_mapping(*args):
            now[0] = 2.
            return None

        with patch('run_cosize.time.perf_counter', side_effect=lambda: now[0]), \
                patch('run_cosize.fit_into', side_effect=slow_mapping), patch('run_cosize.relation_front') as search:
            out = fixed_aspect(self.limited, 500, self.length, 100, 2, 60, 1,
                               self.anchor, resolution=16, deadline=1.)
        search.assert_not_called()
        self.assertEqual(out['fv_solves'], 1)
        self.assertEqual(out['history'][-1]['stop'], 'deadline')
        self.assertEqual(out['best']['step'], 0)

    def test_fixed_search_keeps_the_early_seed_when_the_rest_of_the_batch_is_late(self):
        from run_cosize import fixed_aspect
        now = [0.]
        def late_batch(problem, gap, budget, seed, starts, opts):
            probe = opts['seed_check']
            w, h = (s/1000 for s in problem.carrier_um)
            probe.records.append(dict(arm='wire_seed', certified=True, width_mm=w, height_mm=h,
                                      cost_usd=schedule.interposer_cost(w, h)['total_usd'], fv_solves=1))
            now[0] = 2.
            return [], dict(solves=3)
        with patch('time.perf_counter', side_effect=lambda: now[0]), patch('run_cosize.relation_front', late_batch):
            out = fixed_aspect(self.limited, 500, self.length, 30, 2, 5, 1, self.anchor, resolution=16,
                               deadline=1., seed_first=True)
        self.assertEqual(out['best']['arm'], 'wire_seed')
        late, = [r for r in out['history'] if r.get('after_deadline')]
        self.assertEqual((late['certified'], late['fv_solves']), (False, 2))
        self.assertEqual(out['fv_solves'], 1 + sum(r.get('fv_solves', 0) for r in out['history']))

    def test_a_late_anchor_is_charged_but_cannot_enter_either_comparison(self):
        from run_cosize import fixed_aspect
        for module in ('chiplet_floorplanning.placement.schedule', 'run_cosize'):
            with patch(module + '.verify_anchor', return_value=dict(ok=True, fv_solves=1)), \
                    patch(module + '.time.perf_counter', side_effect=[0., 2.]):
                if module == 'run_cosize':
                    out = fixed_aspect(self.limited, 500, self.length, 1, 2, 5, 1, self.anchor, deadline=1.)
                else:
                    out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=1, deadline=1.)
            self.assertEqual(out['fv_solves'], 1)
            self.assertFalse(out['anchor']['ok'])
            self.assertTrue(out['anchor']['after_deadline'])
            self.assertIsNone(out['best'])

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
                               deadline=time.perf_counter() + 60, threads=1, workers=1, resolution=16, v8=True)
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
                               deadline=time.perf_counter() + 60, threads=1, workers=1, resolution=16, v8=True)
        first = calls[0]
        self.assertTrue(any(a < first for a in calls))                 # the lower half is still tried
        self.assertTrue(any(a > first for a in calls))                 # and towards the certified side first


if __name__ == '__main__':
    unittest.main()
