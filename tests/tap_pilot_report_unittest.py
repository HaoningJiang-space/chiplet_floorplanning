from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from report_tap_online_pilot import analyze, pooled_front, CASES, METHODS, SEEDS


def synthetic_fixture():
    records = []
    for case_index, case in enumerate(CASES):
        for method_index, method in enumerate(METHODS):
            for seed_index, seed in enumerate(SEEDS):
                capped = method == 'sa' and seed_index == 4
                queries = 40 if capped else 64
                initial_hv = .4 + seed_index*.01
                gain = .1 + method_index*.05
                points = [dict(query_index=i, peak_c=80+case_index*20-i*.1,
                               centre_span_mm=20+i*.1) for i in range(queries)]
                def metric(hv, n):
                    return dict(hypervolume=hv, best_peak_c=points[n-1]['peak_c'], best_centre_span_mm=20.,
                                archive_query_indices=list(range(n)), archive_points_outside_reference=0)
                checkpoints = [dict(queries=n, **metric(initial_hv+gain*(n-16)/48, n))
                               for n in (16, 32, 64) if n <= queries]
                records.append(dict(case=case, method=method, seed=seed,
                    status='stopped_at_limit' if capped else 'complete_query_budget', queries=queries,
                    proposals=10000 if capped else 100+20*method_index, cache_hits=4,
                    illegal_proposals=10000-queries-4 if capped else 100+20*method_index-queries-4,
                    elapsed_seconds=50+seed_index*3+method_index*5,
                    checkpoints=checkpoints, final_metrics=metric(initial_hv+gain, queries), points=points))
    return dict(status='complete_pilot_verified', verified_runs=45, policy_replay=True,
                synthetic_fixture=True, records=records)


class PilotReportTest(unittest.TestCase):
    def test_reject_partial_and_missing_seed(self):
        data = synthetic_fixture()
        data['status'] = 'partial_verification_not_comparative'
        with self.assertRaises(ValueError):
            analyze(data)
        data = synthetic_fixture()
        data['records'].pop()
        with self.assertRaises(ValueError):
            analyze(data)

    def test_pairing_retains_caps_and_exact_differences(self):
        data = synthetic_fixture()
        result = analyze(data)
        self.assertEqual(len(result['paired_vs_random']), 6)
        sa = next(p for p in result['paired_vs_random'] if p['case'] == CASES[0] and p['method'] == 'sa')
        self.assertEqual(sa['wins'], 5)
        self.assertEqual(sa['both_completed'], [True, True, True, True, False])
        for value in sa['final_hypervolume_difference']['values']:
            self.assertAlmostEqual(value, .05)
        summary = next(p for p in result['summaries'] if p['case'] == CASES[0] and p['method'] == 'sa')
        self.assertEqual(summary['capped'], 1)
        self.assertEqual(summary['queries']['minimum'], 40)

    def test_initial_metric_mismatch_is_not_paired(self):
        data = synthetic_fixture()
        data['records'][0]['checkpoints'][0]['hypervolume'] += .01
        with self.assertRaisesRegex(ValueError, 'Initialization'):
            analyze(data)

    def test_pooled_front_preserves_ties_and_excludes_dominated_point(self):
        records = [dict(method='random', seed=1, points=[dict(query_index=i, peak_c=t, centre_span_mm=s)
                   for i, (t, s) in enumerate([(77., 31.), (77.-4e-11, 31.), (76., 40.), (78., 40.)])])]
        front = pooled_front(records)
        self.assertEqual(len(front), 2)
        self.assertEqual(sorted(p['query_index'] for b in front for p in b['members']), [0, 1, 2])
