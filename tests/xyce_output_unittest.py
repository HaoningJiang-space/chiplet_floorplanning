from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))

from validation.xyce_output import read_wave, execute, warning_inventory


class XyceOutputTest(unittest.TestCase):
    def test_reordered_columns_rejected_even_with_same_shape(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'wave.csv'
            p.write_text('TIME,V(B),V(A)\n0,1,0\n1,0,1\n')
            with self.assertRaisesRegex(ValueError, 'identity/order'):
                read_wave(p, ['V(A)', 'V(B)'])

    def test_duplicate_column_rejected(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'wave.csv'
            p.write_text('TIME,V(A),V(A)\n0,1,0\n1,0,1\n')
            with self.assertRaises(ValueError):
                read_wave(p, ['V(A)', 'V(B)'])

    def test_expected_identity_accepted(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'wave.csv'
            p.write_text('TIME,V(A),V(B)\n0,1,0\n1,0,1\n')
            self.assertEqual(read_wave(p, ['V(a)', 'V(b)']).shape, (2, 3))

    def test_timeout_retains_partial_log_and_unknown_result(self):
        def timeout(*args, **kwargs):
            kwargs['stdout'].write('partial diagnostic\n')
            kwargs['stdout'].flush()
            raise subprocess.TimeoutExpired(args[0], 60)
        with TemporaryDirectory() as tmp:
            with patch('validation.xyce_output.subprocess.run', side_effect=timeout):
                result = execute('xyce.exe', tmp)
            self.assertEqual(result['status'], 'execution_timeout')
            self.assertIsNone(result['returncode'])
            self.assertIn('partial diagnostic', (Path(tmp)/'xyce.log').read_text())

    def test_nonzero_exit_is_failure(self):
        with TemporaryDirectory() as tmp:
            with patch('validation.xyce_output.subprocess.run', return_value=subprocess.CompletedProcess([], 2)):
                self.assertEqual(execute('xyce.exe', tmp)['status'], 'execution_failed')

    def test_new_warning_is_not_admitted_by_count(self):
        known = warning_inventory('Netlist warning: Source conductance reset to 1.0e3 mho\n***** End')
        unknown = warning_inventory('Netlist warning: TEMP parameter ignored\n***** End')
        self.assertEqual(len(known['messages']), len(unknown['messages']))
        self.assertFalse(known['unknown_messages'])
        self.assertTrue(unknown['unknown_messages'])
        self.assertFalse(known['physical_harmlessness_proven'])

    def test_known_substring_does_not_admit_extra_diagnostic(self):
        result = warning_inventory('Netlist warning: Source conductance reset to 1.0e3 mho; TEMP ignored\n')
        self.assertTrue(result['unknown_messages'])

    def test_other_prefix_and_case_fail_closed(self):
        for prefix in ('WARNING:', 'Device Warning:', 'Solver warning:'):
            with self.subTest(prefix=prefix):
                result = warning_inventory(prefix+' Source conductance reset to 1.0e3 mho\n')
                self.assertEqual(len(result['unknown_messages']), 1)

    def test_warning_limit_is_incomplete_diagnostics(self):
        result = warning_inventory('Maximum warning count has been exceeded and will no longer be displayed\n')
        self.assertTrue(result['unknown_messages'])

    def test_wrapped_known_message_has_exact_normalized_identity(self):
        result = warning_inventory('Netlist warning in file\n C:/model.spice at or near line 31\n Device instance X:A:M1: Source conductance\n reset to 1.0e3 mho\n***** End')
        self.assertFalse(result['unknown_messages'])


if __name__ == '__main__':
    unittest.main()
