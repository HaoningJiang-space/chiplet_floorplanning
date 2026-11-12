from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from compare_transistor_layouts import compare_rows


class PairedLayoutTest(unittest.TestCase):
    def rows(self, window, bias):
        return [dict(step_ps=step, lane=f'{g}_{lane}', edge=edge,
                     setup_window_ns=window, hold_window_ns=20-window,
                     setup_window_difference_ps=bias, hold_window_difference_ps=-bias)
                for step in (5., 2.5) for g in range(2) for lane in range(4)
                for edge in ('rise', 'fall')]

    def test_common_bias_cancels_in_layout_difference(self):
        report = compare_rows(self.rows(10, 100), self.rows(10.1, 100))
        self.assertEqual(report['opposite_path_orderings'], 0)
        self.assertAlmostEqual(report['max_abs_differential_model_discrepancy_ps'], 0)
        self.assertAlmostEqual(report['worst_window_comparison']['setup']['spice_b_minus_a_ps'], 100)
        self.assertAlmostEqual(report['worst_window_comparison']['hold']['spice_b_minus_a_ps'], -100)

    def test_layout_dependent_discrepancy_reverses_ordering(self):
        report = compare_rows(self.rows(10, 0), self.rows(10.1, 200))
        self.assertEqual(report['opposite_path_orderings'], 32)
        self.assertTrue(report['worst_window_comparison']['setup']['opposite_ordering'])
        self.assertAlmostEqual(report['max_abs_differential_model_discrepancy_ps'], 200)

    def test_missing_or_duplicate_paths_rejected(self):
        rows = self.rows(10, 0)
        for bad in (rows[:-1], rows[:-1]+[rows[0]]):
            with self.assertRaisesRegex(ValueError, 'domain'):
                compare_rows(rows, bad)

    def test_nonfinite_windows_cannot_claim_ordering(self):
        rows = self.rows(10, 0)
        rows[0]['hold_window_ns'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'finite'):
            compare_rows(rows, self.rows(10, 0))


if __name__ == '__main__':
    unittest.main()
