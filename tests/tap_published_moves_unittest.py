import copy
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from tap_online import Evaluator, LimitReached
from tap_published_moves import NeighbourhoodExhausted, propose, acceptance, run_tap_policy


class PublishedMovesTest(unittest.TestCase):
    def test_upstream_adaptive_acceptance_and_degenerate_range(self):
        import math
        old = dict(peak_c=75, centre_span_mm=20)
        new = dict(peak_c=79, centre_span_mm=30)
        self.assertAlmostEqual(acceptance(old, new, ((75, 79), (20, 30)), .5), math.exp(-2))
        self.assertAlmostEqual(acceptance(old, new, ((75, 79), (20, 20)), 1), math.exp(-10))
        new = dict(peak_c=81, centre_span_mm=10)
        self.assertEqual(acceptance(old, new, ((75, 81), (10, 20)), 1), 1)

    def test_tap_complete_budget_and_common_metrics(self):
        from tap_online_unittest import OnlineTest, SCALE
        from tap_r3_metrics import summarize, paired_difference
        fixture = OnlineTest()
        def solve(p):
            return dict(peak_power_layer_c=70+sum(x['centre_x_um'] for x in p)/10000,
                        numerical_admission_passed=True)
        result = run_tap_policy(fixture.domain(), fixture.initial(), SCALE, 23, solve)
        self.assertEqual((result['status'], result['queries']), ('complete_query_budget', 64))
        self.assertTrue(result['decisions'])
        score = summarize(result, SCALE)
        self.assertGreaterEqual(score['hypervolume_gain_from_initial'], 0)
        self.assertEqual(score['distinct_thermal_states'], 64)
        self.assertEqual(score['hypervolume'], result['final_metrics']['hypervolume'])
        self.assertEqual(paired_difference(score, score)['hypervolume'], 0)
        self.assertAlmostEqual(score['legal_proposal_fraction']+score['illegal_proposal_fraction'], 1)

    def evaluator(self, side=6000, cap=100):
        domain = dict(interposer_side_um=side, centre_grid_um=1000, minimum_gap_um=100,
                      rotations_deg=[0, 90, 180, 270], connection_wire_demands=[[0]],
                      chiplets=[dict(id=0, core_width_um=2000, core_height_um=2000,
                                     bump_ring_um=0, power_w=1)])
        scale = dict(temperature_origin_c=0, temperature_scale_k=1, span_origin_mm=0,
                     span_scale_mm=1, hypervolume_reference=[2, 2])
        # No thermal solve should be needed in rejection-only controls.
        return Evaluator(domain, lambda p: (_ for _ in ()).throw(AssertionError('unexpected solve')),
                         64, scale, proposal_cap=cap)

    def placement(self):
        return [dict(id=0, centre_x_um=1000, centre_y_um=1000, rotation_deg=0)]

    def test_exhausted_neighbourhood_is_not_global_infeasibility(self):
        ev = self.evaluator(side=2000)
        p = self.placement()
        with self.assertRaises(NeighbourhoodExhausted):
            propose(ev, p, random.Random(1), mode='close')
        self.assertEqual((ev.proposals, ev.illegal, ev.solve_attempts), (4, 4, 0))
        self.assertEqual(p, self.placement())

    def test_retry_fallback_charges_every_candidate_and_keeps_return_type(self):
        ev = self.evaluator()
        calls = []
        def evaluate(p, operator):
            calls.append((copy.deepcopy(p), operator))
            return None if operator == 'tap_jump' else dict(placement=p, peak_c=70)
        ev.evaluate = evaluate
        p = self.placement()
        result = propose(ev, p, random.Random(2), mode='jump', jump_attempts=3)
        self.assertEqual([op for _, op in calls], ['tap_jump']*3+['tap_close'])
        self.assertEqual(result['placement'], calls[-1][0])
        self.assertEqual(p, self.placement())

    def test_budget_exception_propagates_during_close_scan(self):
        ev = self.evaluator(side=2000, cap=2)
        with self.assertRaises(LimitReached):
            propose(ev, self.placement(), random.Random(3), mode='close')
        self.assertEqual(ev.proposals, 2)

    def test_solver_failure_is_not_retried_or_relabelled(self):
        ev = self.evaluator()
        def fail(p, operator):
            raise RuntimeError('thermal failed unknown')
        ev.evaluate = fail
        with self.assertRaisesRegex(RuntimeError, 'thermal failed unknown'):
            propose(ev, self.placement(), random.Random(4), mode='jump')


if __name__ == '__main__':
    unittest.main()
