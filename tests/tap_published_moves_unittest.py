import copy
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from tap_online import Evaluator, LimitReached
from tap_published_moves import NeighbourhoodExhausted, propose


class PublishedMovesTest(unittest.TestCase):
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
