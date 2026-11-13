from copy import deepcopy
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from import_atplace_cases import parse_case as import_case
from atplace_import_unittest import BLOCKS, POWER, NETS
from atplace_search import Ledger, Space, CostLimit, identities, profile, ranks_and_crowding, run_policy


class AtplaceSearchTest(unittest.TestCase):
    def setUp(self):
        self.source = import_case('test', BLOCKS, POWER, NETS)
        self.base = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
                     dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        self.plan = dict(seed=2026111200, gap_um=1000, grid_um=1000, population=2,
                         proposal_cap=10, candidate_check_cap=10000, pin_call_cap=20,
                         thermal_budget=4, length_cap_m=.0072, temperature_cap_c=80.)
        self.solve = lambda data: dict(numerical_admission_passed=True, peak_power_layer_c=80.)

    def test_cache_hit_keeps_both_full_states_and_constrained_witnesses(self):
        ledger = Ledger(self.source, self.plan, self.solve)
        a = ledger.submit(self.base, ledger.begin('initial'))
        rotated = deepcopy(self.base)
        rotated[0]['rotation_deg'] = 180
        b = ledger.submit(rotated, ledger.begin('rotation'))
        self.assertEqual(len(ledger.rows), 2)
        self.assertEqual(len(ledger.thermal_records), 1)
        self.assertNotEqual(a['layout_key'], b['layout_key'])
        self.assertEqual(a['thermal_key'], b['thermal_key'])
        self.assertEqual(a['thermal_solve_id'], b['thermal_solve_id'])
        self.assertEqual((a['pin_length_m'], b['pin_length_m']), (.0072, .0088))
        self.assertTrue(b['thermal_cache_hit'])
        self.assertEqual(profile(ledger.rows, .0072, 80)['temperature_at_length']['selected']['row_index'], 0)
        self.assertIsNone(ledger.submit(rotated, ledger.begin('duplicate')))
        self.assertEqual(ledger.pin_calls, 2)
        self.assertEqual(ledger.events[-1]['status'], 'duplicate_full_state')

    def test_constraints_select_joint_rows_and_preserve_missing(self):
        rows = [dict(row_index=0, peak_c=90., pin_length_m=1.),
                dict(row_index=1, peak_c=70., pin_length_m=3.)]
        p = profile(rows, 1., 70.)
        self.assertEqual(p['temperature_at_length']['selected'], rows[0])
        self.assertEqual(p['length_at_temperature']['selected'], rows[1])
        self.assertIsNone(profile(rows, .9, 69.)['temperature_at_length']['selected'])
        rank, _ = ranks_and_crowding(rows+[dict(row_index=2, peak_c=91., pin_length_m=4.)])
        self.assertEqual(rank, {0:0, 1:0, 2:1})

    def test_pin_and_candidate_limits_charge_actual_work(self):
        self.plan['pin_call_cap'] = 1
        ledger = Ledger(self.source, self.plan, self.solve)
        ledger.score(self.base)
        with self.assertRaises(CostLimit):
            ledger.score(self.base)
        self.assertEqual(ledger.pin_calls, 1)
        space = Space(self.source, 1000, 1000, 3)
        with self.assertRaises(CostLimit):
            space.construct(random.Random(1))
        self.assertEqual(space.checks, 3)

    def test_guidance_uses_pin_cap_but_does_not_change_legal_domain(self):
        space = Space(self.source, 1000, 1000, 10000)
        calls = []
        def score(p):
            value = p[0]['centre_x_um']/1000
            calls.append(value)
            return dict(total_pin_manhattan_m=value)
        chosen = space.mutate(self.base, 0, random.Random(5), True, score, 3.)
        self.assertEqual(len(calls), 4)
        if any(v <= 3 for v in calls):
            self.assertLessEqual(chosen['centre_x_um']/1000, 3)
        else:
            self.assertEqual(chosen['centre_x_um']/1000, min(calls))

    def test_off_grid_and_failed_thermal_are_not_successes(self):
        ledger = Ledger(self.source, self.plan, self.solve)
        bad = deepcopy(self.base)
        bad[0]['centre_x_um'] += 1
        self.assertIsNone(ledger.submit(bad, ledger.begin('off_grid')))
        self.assertEqual(ledger.pin_calls, 0)
        other = deepcopy(self.base)
        other[0]['centre_y_um'] += 1000
        self.plan['initialization'] = dict(placements=[self.base, other], candidate_checks=0,
                                           construction_attempts=1, elapsed_seconds=0.)
        result = run_policy(self.source, self.plan, 'nsga2_legal',
                            lambda data: dict(numerical_admission_passed=False, peak_power_layer_c=80.))
        self.assertEqual(result['status'], 'failed_unknown')
        self.assertEqual(result['effort']['solve_attempts'], 1)
        self.assertEqual(result['rows'], [])

    def test_policy_caps_without_replacing_the_run(self):
        other = deepcopy(self.base)
        other[0]['centre_y_um'] += 1000
        self.plan['initialization'] = dict(placements=[self.base, other], candidate_checks=0,
                                           construction_attempts=2, elapsed_seconds=0.)
        self.plan['proposal_cap'] = 3
        result = run_policy(self.source, self.plan, 'nsga2_legal', self.solve)
        self.assertEqual(result['status'], 'capped')
        self.assertEqual(result['reason'], 'proposal_cap')
        self.assertEqual(result['effort']['thermal_queries'], 2)
        self.assertEqual(result['effort']['proposals'], 3)
        self.assertEqual(result['effort']['initial_retry_proposals'], 1)
        self.assertEqual(len(result['rows']), 2)

    def test_both_policies_can_finish_a_small_fresh_thermal_budget(self):
        other = deepcopy(self.base)
        other[0]['centre_y_um'] += 1000
        self.plan.update(proposal_cap=200, pin_call_cap=200, candidate_check_cap=100000)
        self.plan['initialization'] = dict(placements=[self.base, other], candidate_checks=0,
                                           construction_attempts=1, elapsed_seconds=0.)
        for method in ('nsga2_legal', 'nsga2_pin_guided'):
            result = run_policy(self.source, self.plan, method, self.solve)
            self.assertEqual(result['status'], 'complete_thermal_budget')
            self.assertEqual(result['effort']['thermal_queries'], 4)
            self.assertGreaterEqual(len(result['rows']), 4)

    def test_cached_orientations_can_form_offspring_generations(self):
        other = deepcopy(self.base)
        other[0]['centre_y_um'] += 1000
        self.plan['initialization'] = dict(placements=[self.base, other], candidate_checks=0,
                                           construction_attempts=1, elapsed_seconds=0.)
        self.plan.update(proposal_cap=24, pin_call_cap=100)
        def rotate_only(space, placement, index, rng, guided, score, cap):
            p = deepcopy(placement[index])
            p['rotation_deg'] = (p['rotation_deg']+180) % 360
            return p
        with patch.object(Space, 'mutate', new=rotate_only):
            result = run_policy(self.source, self.plan, 'nsga2_legal', self.solve)
        self.assertEqual(result['effort']['thermal_queries'], 2)
        self.assertTrue(any(r['thermal_cache_hit'] for r in result['rows']))
        self.assertGreaterEqual(result['complete_generations'], 1)
        self.assertEqual(result['status'], 'capped')


if __name__ == '__main__':
    unittest.main()
