"""Analytic crossing and finite-difference controls independent of downloaded PDKs."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.validation.pad_diagnostics import (
    METRICS, finite_difference, measurement_convention, nominal_comparison,
    source_measurements, table_reference,
)


def header(derate=1):
    result = f'library(test) {{ time_unit:"1ns"; capacitive_load_unit(1,"pf"); slew_derate_from_library:{derate};'
    for edge in ('rise', 'fall'):
        for attr, value in (('input_threshold_pct', 25), ('output_threshold_pct', 75),
                            ('slew_lower_threshold_pct', 10), ('slew_upper_threshold_pct', 90)):
            result += f'{attr}_{edge}:{value};'
    return result + '}'


class PadDiagnosticTests(unittest.TestCase):
    def convention(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.lib'
            path.write_text(text)
            return measurement_convention(path)

    def test_source_thresholds_change_delay_by_hand_calculated_amounts(self):
        t = np.linspace(0, 70, 7001)
        vin = np.interp(t, [0, 10, 11, 40, 41, 70], [0, 0, 3.3, 3.3, 0, 0])
        vout = np.interp(t, [0, 12, 14, 42, 44, 70], [0, 0, 1.8, 1.8, 0, 0])
        metrics = source_measurements(np.column_stack((t*1e-9, vin, vout)), self.convention(header()), 3.3, 1.8)
        self.assertAlmostEqual(metrics['rise_delay_ns'], 3.25)
        self.assertAlmostEqual(metrics['fall_delay_ns'], 1.75)
        self.assertAlmostEqual(metrics['rise_slew_ns'], 1.6)
        self.assertAlmostEqual(metrics['fall_input_slew_ns'], 0.8)

    def test_unsupported_units_and_derate_fail_closed(self):
        for text in (header(0.5), header().replace('1ns', '1ps'),
                     header().replace('75;', '101;'), header().replace('"pf"', '"ff"')):
            with self.assertRaises(ValueError):
                self.convention(text)

    def test_competing_load_mapping_is_rejected_outside_source_table(self):
        arc = ''.join(f'{kind}(t) {{ index_1("0.1, 1"); index_2("3, 6"); values("1, 2", "3, 4"); }}'
                      for kind in ('cell_rise', 'cell_fall', 'rise_transition', 'fall_transition'))
        a = table_reference(arc, 0.5, 1, 3, 'external_plus_self')
        b = table_reference(arc, 0.5, 1, 3, 'external_only')
        self.assertTrue(a['in_domain'])
        self.assertFalse(b['in_domain'])
        self.assertIsNone(b['metrics'])
        self.assertEqual(b['status'], 'table_domain_rejected')

    def test_matching_changes_do_not_repair_absolute_mismatch(self):
        a = {k: 1.0 for k in METRICS}
        b = {k: 1.2 for k in METRICS}
        ref_a = dict(in_domain=True, metrics={k: 2.0 for k in METRICS})
        ref_b = dict(in_domain=True, metrics={k: 2.2 for k in METRICS})
        noise = {k: 0.001 for k in METRICS}
        delta = finite_difference(a, b, ref_a, ref_b, noise, noise)
        self.assertFalse(delta['physical_accuracy_qualified'])
        self.assertLess(abs(delta['metrics']['rise_delay_ns']['residual_ns']), 1e-12)
        self.assertFalse(nominal_comparison(a, ref_a, 3)['agreement']['passed'])

    def test_near_zero_delta_has_absolute_empirical_screen_not_relative_pass(self):
        a = {k: 1.0 for k in METRICS}
        b = {k: 1.001 for k in METRICS}
        ref = dict(in_domain=True, metrics=a)
        noise = {k: 0.0003 for k in METRICS}
        delta = finite_difference(a, b, ref, ref, noise, noise)
        row = delta['metrics']['rise_delay_ns']
        self.assertEqual(row['liberty_delta_ns'], 0)
        self.assertAlmostEqual(row['endpoint_step_change_sum_ns'], 0.0006)
        self.assertTrue(row['residual_exceeds_observed_step_changes'])
        self.assertNotIn('passed', delta)


if __name__ == '__main__':
    unittest.main()
