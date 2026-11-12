import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from compare_xyce_hot_layouts import classify, compare


class LayoutOrderingTest(unittest.TestCase):
    def test_interaction_need_not_reverse_order(self):
        row = classify([10, 10.1], [12, 12.1], True, .02)
        self.assertEqual(row['ordering'], 'stable')
        self.assertEqual(row['interaction_status'], 'observed_interaction')
        self.assertEqual(row['physical_uncertainty'], 'unquantified')

    def test_reversal_requires_resolved_sign_on_both_steps(self):
        self.assertEqual(classify([10, 10.1], [-2, -2.1], True, .02)['ordering'], 'changed')
        self.assertEqual(classify([10, 10.1], [-.01, .01], True, .02)['ordering'], 'unresolved')

    def test_failed_control_or_small_margin_cannot_resolve(self):
        self.assertEqual(classify([10, 10], [-10, -10], False, .02)['ordering'], 'unresolved')
        self.assertEqual(classify([.01, .01], [.02, .02], True, .02)['ordering'], 'unresolved')

    def test_incomplete_path_domain_rejected(self):
        with self.assertRaisesRegex(ValueError, 'path domain'):
            compare(dict(complete=True, diagnostics_admitted=True, paths=[]), {}, True, .02)

    def test_minimum_reselects_critical_path_after_temperature_change(self):
        def report(offset):
            rows = []
            for step in (5., 2.5):
                for g in range(2):
                    for lane in range(4):
                        for edge in ('rise', 'fall'):
                            for kind in ('setup', 'hold'):
                                cold = 10 + g + lane*.01 + offset
                                hot = cold + (1 if lane == 0 else 0)
                                rows.append(dict(step_ps=step, lane=f'{g}_{lane}', edge=edge,
                                    window=kind, cold_window_ns=cold, hot_window_ns=hot,
                                    sta_cold_window_ns=cold, sta_hot_window_ns=hot))
            return dict(complete=True, diagnostics_admitted=True, paths=rows)
        result = compare(report(0), report(.1), True, .02)
        for row in result['minimum_windows']:
            self.assertEqual(row['critical_paths_a_b']['cold_2.5ps'][0]['lane'], '0_0')
            self.assertEqual(row['critical_paths_a_b']['hot_2.5ps'][0]['lane'], '0_1')
            self.assertEqual(row['ordering'], 'stable')
            self.assertAlmostEqual(row['sta_pair_difference_ps']['cold'], 100)
            self.assertAlmostEqual(row['sta_pair_difference_ps']['hot'], 100)
            self.assertAlmostEqual(row['interaction_model_difference_ps'], 0)


if __name__ == '__main__':
    unittest.main()
