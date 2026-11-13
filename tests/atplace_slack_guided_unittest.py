from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_slack_guided import guided_slack_crossover, run_policy
from atplace_search import CostLimit, Space
from atplace_pin_geometry import placement_geometry
from import_atplace_cases import parse_case as import_case
from atplace_import_unittest import BLOCKS, POWER, NETS


class FixedDraw:
    def randrange(self, n):
        return 0

    def sample(self, items, n):
        return list(items)[:n]

    def choice(self, items):
        return items[-1]


class GuidedSlackTest(unittest.TestCase):
    def setUp(self):
        self.source = dict(interposer_width_um=15000, interposer_height_um=10000,
            chiplets=[dict(name=f'd{i}', width_um=2000, height_um=2000) for i in range(3)])
        def pose(coords):
            return [dict(chiplet=f'd{i}', centre_x_um=x*1000, centre_y_um=y*1000, rotation_deg=0)
                    for i, (x, y) in enumerate(coords)]
        self.a, self.b = pose([(2, 2), (7, 4), (12, 8)]), pose([(12, 2), (3, 7), (7, 3)])

    def run_operator(self, values, cap, a=None, b=None, limit=100):
        calls, receipt = [], {}
        def score(p):
            placement_geometry(self.source, p, 1000)
            calls.append(deepcopy(p))
            return dict(total_pin_manhattan_m=values[len(calls)-1])
        space = Space(self.source, 1000, 1000, limit)
        p = guided_slack_crossover(space, a or self.a, b or self.b, FixedDraw(), receipt, score, cap)
        return p, receipt, calls, space

    def test_prefers_feasible_candidates_including_the_exact_boundary(self):
        p, r, calls, space = self.run_operator([9., 2., 8., 4.], 4.)
        self.assertEqual(len(calls), 4)
        self.assertEqual(r['feasible_candidates'], 2)
        self.assertEqual(r['selected_pin_length_m'], 4.)
        self.assertEqual(r['selection_rule'], 'within_length_cap')
        self.assertEqual(p, calls[3])
        self.assertEqual(space.checks, 6)
        self.assertEqual(r['topology_pair_checks'], 6)

    def test_no_feasible_candidate_uses_minimum_length_without_relaxing_threshold(self):
        p, r, calls, _ = self.run_operator([9., 2., 8., 4.], 1.)
        self.assertEqual(r['feasible_candidates'], 0)
        self.assertEqual(r['selection_rule'], 'minimum_length')
        self.assertEqual(r['selected_pin_length_m'], 2.)
        self.assertEqual(p, calls[1])

    def test_deduplicates_identical_poses_before_scoring_but_charges_every_decode(self):
        before = deepcopy((self.source, self.a))
        p, r, calls, space = self.run_operator([5.], 6., b=self.a)
        self.assertEqual(len(r['candidates']), 4)
        self.assertEqual((len(calls), r['pin_calls'], r['distinct_candidates']), (1, 1, 1))
        self.assertEqual(space.checks, 6)
        self.assertEqual(p, self.a)
        self.assertEqual((self.source, self.a), before)

    def test_partial_geometry_or_pin_pool_cannot_select_a_prefix(self):
        for kind in ('geometry', 'pin'):
            r, calls = {}, []
            space = Space(self.source, 1000, 1000, 5 if kind == 'geometry' else 100)
            def score(p):
                if calls:
                    raise CostLimit('pin_call_cap')
                calls.append(p)
                return dict(total_pin_manhattan_m=0.)
            with self.assertRaises(CostLimit):
                guided_slack_crossover(space, self.a, self.b, FixedDraw(), r, score, 1.)
            self.assertEqual(r['selection'], 'incomplete')
            self.assertNotIn('placement', r)
            self.assertEqual(len(calls), 0 if kind == 'geometry' else 1)

    def test_bounded_search_charges_pool_pins_without_extra_thermal_calls(self):
        source = import_case('test', BLOCKS, POWER, NETS)
        a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
             dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        b = deepcopy(a)
        b[0]['centre_y_um'] += 1000
        plan = dict(seed=2026111200, gap_um=1000, grid_um=1000, population=2,
            proposal_cap=200, candidate_check_cap=100000, pin_call_cap=1000, thermal_budget=4,
            length_cap_m=.0072, temperature_cap_c=80., initialization=dict(placements=[a, b],
            construction_attempts=1, candidate_checks=0, elapsed_seconds=0.))
        result = run_policy(source, plan, lambda d: dict(numerical_admission_passed=True, peak_power_layer_c=80.))
        self.assertEqual(result['status'], 'complete_thermal_budget')
        self.assertEqual(result['effort']['thermal_queries'], 4)
        self.assertEqual(result['effort']['illegal_proposals'], 0)
        self.assertGreater(result['effort']['crossover_pin_calls'], 0)
        self.assertLessEqual(result['effort']['crossover_pin_calls'], result['effort']['prescreen_pin_calls'])
        self.assertEqual(result['effort']['pin_calls'], result['effort']['prescreen_pin_calls']+len(result['rows']))


if __name__ == '__main__':
    unittest.main()
