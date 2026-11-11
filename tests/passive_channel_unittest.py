import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess
from tempfile import TemporaryDirectory
import json

import numpy as np
from scipy.signal import lsim

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.passive_channel import (Channel, VDD, network, state_system, ledger,
                                        crossings, frequency_checks, continuum_transfer)
from validate_passive_channel import simulate


class PassiveChannelTest(unittest.TestCase):
    def test_timeout_is_retained_as_failed_run_with_log(self):
        def fail(*args, **kwargs):
            kwargs['stdout'].write(b'An unfinished solver diagnostic.\n')
            raise subprocess.TimeoutExpired(args[0], 180)
        with TemporaryDirectory() as directory, patch('validate_passive_channel.subprocess.run', side_effect=fail):
            root = Path(directory)
            result = simulate(root, Path('unused'), root, Channel(3, 25, 100), 16, 'RLC', .5, None)
            self.assertTrue(result['timed_out'])
            self.assertFalse(result['completed'])
            self.assertFalse(result['numerical_gates_passed'])
            saved = json.loads((root / result['name'] / 'measurement.json').read_text())
            self.assertEqual(saved, result)
            self.assertIn('unfinished solver', (root / result['name'] / 'ngspice.log').read_text())

    def test_single_rc_analytic_response_and_energy(self):
        # No wire: one 2 pF capacitor charged by an ideal 3.3 V step through 50 ohm.
        cap, driver = 2e-12, 50.
        t = np.linspace(0., 1e-9, 100001)
        c, r, l, b = np.array([cap]), np.array([]), np.array([]), np.zeros((1, 0))
        a, drive = state_system(c, r, l, b, driver)
        _, v, _ = lsim((a, drive[:, None], [[1.]], [[0.]]), U=np.full(len(t), VDD), T=t*1e9)
        expected = VDD * (1-np.exp(-t/(driver*cap)))
        np.testing.assert_allclose(v, expected, atol=1e-10)
        current = (VDD-v)/driver
        result = ledger(t, np.full(len(t), VDD), v[:, None], current,
                        np.empty((len(t), 0)), c, r, l, b, driver)
        self.assertTrue(result['gates_passed'])
        self.assertAlmostEqual(result['source_energy_j']/(cap*VDD**2), 1-np.exp(-10), places=7)
        self.assertAlmostEqual(result['driver_heat_j']/(.5*cap*VDD**2), 1-np.exp(-20), places=7)

    def test_reversed_current_and_missing_load_detected(self):
        t = np.linspace(0., 1e-9, 10001)
        c, r, l, b = np.array([2e-12]), np.array([]), np.array([]), np.zeros((1, 0))
        v = VDD*(1-np.exp(-t/1e-10))
        current = (VDD-v)/50
        for source, cap in [(-current, c), (current, c/2), (current, c*2)]:
            report = ledger(t, np.full(len(t), VDD), v[:, None], source,
                            np.empty((len(t), 0)), cap, r, l, b, 50.)
            self.assertFalse(report['gates_passed'])

    def test_positive_parameters_and_finite_values_required(self):
        for invalid in (-1, 0, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                Channel(invalid, 25, 100)
        c, r, l, b = network(Channel(3, 25, 100), 8, 'RLC')
        for cc, rr, ll in [(-c, r, l), (c, -r, l), (c, r, -l)]:
            with self.assertRaises(ValueError):
                state_system(cc, rr, ll, b, 25)

    def test_reference_planes_and_lumped_totals(self):
        spec = Channel(3, 25, 100)
        c, r, l, b = network(spec, 32, 'RLC')
        self.assertAlmostEqual(r.sum(), 5.04)
        self.assertAlmostEqual((c.sum()-spec.load_f)*1e12, 1.0359399740976)
        self.assertAlmostEqual(l.sum()*1e9, .376991118636)
        np.testing.assert_array_equal(b.sum(axis=0), np.zeros(32))
        self.assertAlmostEqual(c[0], (c[-1]-spec.load_f), delta=1e-27)

    def test_mna_against_independent_cascade_and_continuum_limit(self):
        spec = Channel(6, 25, 100)
        for model in ('RC', 'RLC'):
            errors = []
            for n in (8, 16, 32):
                result = frequency_checks(spec, n, model)
                self.assertTrue(result['algebraic_passed'])
                errors.append(max(x['continuum_absolute_error'] for x in result['records']))
            self.assertLess(errors[2], errors[1]/3)
            self.assertLess(errors[1], errors[0]/3)
            self.assertEqual(continuum_transfer(spec, model, 0), 1.)

    def test_zero_inductance_limit(self):
        c, r, l, b = network(Channel(1, 100, 600), 2, 'RLC')
        a, drive = state_system(c, r, l*1e-6, b, 100)
        ar, br = state_system(c, r, np.zeros_like(l), b, 100)
        s = 2j*np.pi*.1  # GHz; state time is ns.
        rlc = np.linalg.solve(s*np.eye(len(drive))-a, drive)[2]
        rc = np.linalg.solve(s*np.eye(len(br))-ar, br)[2]
        self.assertLess(abs(rlc-rc), 1e-8)

    def test_all_recrossings_retained(self):
        t = np.array([0, 1, 1.1, 1.2, 1.3, 3.9, 4, 4.1, 8])*1e-9
        v = np.array([0, 0, 3.3, 0, 3.3, 3.3, 3.3, 0, 0])
        result = crossings(t, v, Channel(3, 25, 100))
        self.assertEqual(len(result['rise']['levels']['0.5']), 3)
        self.assertFalse(result['rise']['scalar_unambiguous'])
        self.assertIsNone(result['rise']['delay_50_ps'])
        self.assertTrue(result['fall']['scalar_unambiguous'])


if __name__ == '__main__':
    unittest.main()
