import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from tap_r3_metrics import diagnostic_contract, constrained_profile, paired_profiles
from report_tap_physical import analyze, aggregate
from run_tap_online import freeze
from run_tap_online_batch import trial_order


def points(values):
    return [dict(query_index=i, peak_c=t, centre_span_mm=l) for i, (t, l) in enumerate(values)]


def contract():
    return diagnostic_contract([dict(centre_span_mm=l, thermal=dict(peak_power_layer_c=t))
                                for t, l in [(70, 10), (80, 20), (90, 30), (100, 40)]])


class PhysicalMetricsTest(unittest.TestCase):
    def test_select_actual_joint_point_not_separate_minima_or_interpolation(self):
        rows = points([(65, 50), (90, 10), (75, 20), (70, 30)])
        result = constrained_profile(rows, contract())
        selected = result['temperature_at_span_budget'][1]['selected']
        self.assertEqual(selected, rows[2])
        self.assertEqual(result['span_at_temperature_cap'][1]['selected'], rows[2])
        # The marginal minima (65 C, 10 mm) do not coexist in any layout.
        self.assertNotEqual(selected, dict(query_index=0, peak_c=65, centre_span_mm=10))

    def test_boundary_and_tie_selection_are_raw_and_deterministic(self):
        rows = points([(60, 20+1e-10), (75, 20), (75, 19), (75, 19)])
        result = constrained_profile(rows, contract())
        self.assertEqual(result['temperature_at_span_budget'][1]['selected']['query_index'], 2)

    def test_missing_attainment_is_null_and_not_global_infeasible(self):
        a = constrained_profile(points([(75, 15)]), contract())
        b = constrained_profile(points([(65, 25)]), contract())
        pair = paired_profiles(a, b)
        self.assertEqual(pair['temperature_at_span_budget'][0]['status'], 'neither_attained')
        self.assertEqual(pair['temperature_at_span_budget'][1]['status'], 'candidate_only_attained')
        self.assertIsNone(pair['temperature_at_span_budget'][1]['temperature_gain_k'])
        self.assertEqual(pair['span_at_temperature_cap'][0]['status'], 'baseline_only_attained')
        result = aggregate([pair], 'temperature_at_span_budget', 'p50')
        self.assertEqual((result['both_attained'], result['candidate_only_attained']), (0, 1))
        self.assertIsNone(result['conditional_median'])

    def test_paired_sign_percent_and_mismatched_constraint(self):
        a = constrained_profile(points([(75, 15)]), contract())
        b = constrained_profile(points([(78, 20)]), contract())
        pair = paired_profiles(a, b)
        self.assertEqual(pair['temperature_at_span_budget'][1]['temperature_gain_k'], 3)
        self.assertEqual(pair['span_at_temperature_cap'][1]['span_reduction_percent'], 25)
        bad = copy.deepcopy(b)
        bad['contract']['span_budgets'][1]['span_budget_mm'] += 1
        with self.assertRaisesRegex(ValueError, 'identical'):
            paired_profiles(a, bad)

    def test_anchor_rule_uses_earlier_observations(self):
        c = contract()
        self.assertEqual([x['span_budget_mm'] for x in c['span_budgets']], [10, 20, 30])
        self.assertEqual([x['temperature_cap_c'] for x in c['temperature_caps']], [70, 80, 90])

    def test_report_pairs_before_median_and_retains_capped_trial(self):
        initial = points([(100, 40)]*16)
        records = []
        for seed, (base, candidate) in enumerate([(80, 79), (90, 92), (95, 94)]):
            for method, value in [('random', base), ('nsga2', candidate)]:
                capped = seed == 2 and method == 'nsga2'
                n = 32 if capped else 64
                rows = initial + [dict(query_index=i, peak_c=value, centre_span_mm=20) for i in range(16, n)]
                records.append(dict(case='test', method=method, seed=seed, queries=n, points=rows,
                    status='stopped_at_limit' if capped else 'complete_query_budget', final_metrics=dict(hypervolume=0)))
        report = analyze(records, {'test': contract()})
        diff = report['contrasts'][0]
        summary = diff['temperature_at_span_budget'][1]
        self.assertEqual(summary['paired_values'], [1, -2, 1])
        self.assertEqual(summary['conditional_median'], 1)
        self.assertEqual(diff['both_complete'], [True, True, False])
        records[0]['points'] = copy.deepcopy(records[0]['points'])
        records[0]['points'][0]['peak_c'] += .1
        with self.assertRaisesRegex(ValueError, 'initialization'):
            analyze(records, {'test': contract()})

    def test_r3_manifest_reuses_inputs_and_has_only_18_new_runs(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.json'
            freeze(path)
            plan = json.loads(path.read_text())
        old = json.loads(Path('docs/evidence/tap-online-plan-v4.json').read_text())
        self.assertEqual(plan['seeds'], old['seeds'][:3])
        self.assertEqual(len(trial_order(plan)), 18)
        for entry, reference in zip(plan['cases'], old['cases']):
            self.assertEqual(entry['domain'], reference['domain'])
            self.assertEqual(entry['scale'], reference['scale'])
            self.assertEqual(entry['initializations'], reference['initializations'][:3])
            self.assertEqual(entry['comparison']['primary_anchor'], 'p50')
