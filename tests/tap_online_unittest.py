import copy
import math
from pathlib import Path
import random
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from tap_online import Evaluator, LimitReached, Space, metrics, ranks_and_crowding, run_policy, select_population
from diagnose_tap_sensitivity import thermal_key


SCALE = dict(temperature_origin_c=0, temperature_scale_k=1, span_origin_mm=0,
             span_scale_mm=1, hypervolume_reference=[2, 2])


def row(t, distance):
    return dict(peak_c=t, centre_span_mm=distance)


class OnlineTest(unittest.TestCase):
    def domain(self):
        return dict(name='test', interposer_side_um=50000, centre_grid_um=10000,
                    minimum_gap_um=100, rotations_deg=[0, 90, 180, 270],
                    chiplets=[dict(id=i, core_width_um=5000, core_height_um=8000,
                                   bump_ring_um=90, power_w=2+i) for i in range(2)],
                    connection_wire_demands=[[0, 1], [1, 0]])

    def initial(self):
        space, rng = Space(self.domain()), random.Random(211)
        seen, initial = set(), []
        while len(initial) < 16:
            p = space.construct(rng)
            if p is not None and thermal_key(p) not in seen:
                seen.add(thermal_key(p))
                initial.append(p)
        return initial

    def test_hypervolume_rectangle_union_and_outside(self):
        result = metrics([row(0, 1), row(1, 0), row(3, -1)], SCALE)
        self.assertEqual(result['hypervolume'], 3)
        self.assertEqual(result['archive_points_outside_reference'], 1)
        self.assertEqual(metrics([row(-1, -1)], SCALE)['hypervolume'], 9)

    def test_rank_crowding_and_elitist_survival(self):
        rows = [row(0, 3), row(1, 2), row(2, 1), row(3, 0), row(4, 4)]
        rank, crowd = ranks_and_crowding(rows)
        self.assertEqual([rank[i] for i in range(5)], [0, 0, 0, 0, 1])
        self.assertTrue(math.isinf(crowd[0]) and math.isinf(crowd[3]))
        self.assertAlmostEqual(crowd[1], 4/3)
        self.assertNotIn(rows[-1], select_population(rows, 4, random.Random(0)))
        _, ties = ranks_and_crowding([row(1, 1)]*3)
        self.assertEqual(list(ties.values()), [0, 0, 0])

    def test_cache_geometry_and_query_budget(self):
        calls = []
        def solve(p):
            calls.append(p)
            return dict(peak_power_layer_c=70., numerical_admission_passed=True)
        initial = self.initial()
        ev = Evaluator(self.domain(), solve, 1, SCALE)
        first = ev.evaluate(initial[0], 'initial')
        turned = copy.deepcopy(initial[0])
        turned[0]['rotation_deg'] = (turned[0]['rotation_deg']+180) % 360
        self.assertIs(ev.evaluate(turned, 'rotate'), first)
        invalid = copy.deepcopy(initial[0])
        invalid[0]['centre_x_um'] = -10000
        self.assertIsNone(ev.evaluate(invalid, 'move'))
        with self.assertRaises(LimitReached):
            ev.evaluate(initial[1], 'move')
        self.assertEqual((len(calls), ev.cache_hits, ev.illegal), (1, 1, 1))

    def test_all_policies_charge_initialization_and_preserve_it(self):
        initial = self.initial()
        original = copy.deepcopy(initial)
        for method in ('random', 'sa', 'nsga2'):
            calls = []
            def solve(p):
                calls.append(thermal_key(p))
                return dict(peak_power_layer_c=70+sum(x['centre_x_um'] for x in p)/10000,
                            numerical_admission_passed=True)
            result = run_policy(self.domain(), initial, SCALE, method, 23, solve, budget=32)
            self.assertEqual(result['status'], 'complete_query_budget', result['reason'])
            self.assertEqual(result['search_seed'], 1000023)
            self.assertEqual(len(calls), 32)
            self.assertEqual(len(set(calls)), 32)
            self.assertEqual(calls[:16], [thermal_key(p) for p in initial])
            self.assertEqual(result['queries']+result['cache_hits']+result['illegal_proposals'], result['proposals'])
            self.assertEqual([c['queries'] for c in result['checkpoints']], [16, 32])
            if method == 'nsga2':
                self.assertEqual(result['generations'], 1)
        self.assertEqual(initial, original)

    def test_proposal_cap_and_solver_failure_are_not_penalties(self):
        def solve(p):
            return dict(peak_power_layer_c=70., numerical_admission_passed=True)
        result = run_policy(self.domain(), self.initial(), SCALE, 'sa', 2, solve, budget=32, proposal_cap=16)
        self.assertEqual((result['status'], result['queries'], result['proposals']), ('stopped_at_limit', 16, 16))
        def fail(p):
            raise RuntimeError('synthetic solver failure')
        result = run_policy(self.domain(), self.initial(), SCALE, 'random', 2, fail, budget=32)
        self.assertEqual((result['status'], result['queries'], result['solve_attempts']), ('failed_unknown', 0, 1))
        self.assertEqual(result['events'][0]['status'], 'thermal_failed_unknown')

    def test_duplicate_initialization_is_rejected(self):
        initial = self.initial()
        initial[-1] = initial[0]
        with self.assertRaises(ValueError):
            run_policy(self.domain(), initial, SCALE, 'random', 2, lambda _: None)
