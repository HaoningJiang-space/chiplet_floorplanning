import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.measured_thermal import (endpoint, longest_interval, predict,
                                        sensitivity, rank_report, network_ledger)


class MeasuredThermalTest(unittest.TestCase):
    def test_uniform_heating_analytic_solution_and_rank_deficiency(self):
        # 2 W/cell, gz=4 W/K, ga=8 W/K gives 0.5+32/8=4.5 K.
        g = np.log([3., 4., 8.])
        p = np.full(16, 2.)
        np.testing.assert_allclose(predict(g, p), 4.5, atol=1e-12)
        self.assertEqual(rank_report(sensitivity(g, p))['rank'], 1)
        r = network_ledger(g, p, 25.)
        self.assertAlmostEqual(r['removed_heat_w'], 32.)

    def test_localized_heat_can_identify_three_reduced_parameters(self):
        p = np.full((2, 16), .2)
        p[0, 0] = 7
        p[1, :4] = 3
        g = np.log([.1, .2, 1.])
        j = sensitivity(g, p)
        self.assertEqual(rank_report(j)['rank'], 3)
        # Central finite differences provide an independent derivative check.
        for n in range(3):
            d = np.eye(3)[n] * 1e-5
            numeric = ((predict(g + d, p) - predict(g - d, p)) / 2e-5).ravel()
            np.testing.assert_allclose(j[:, n], numeric, rtol=1e-7, atol=1e-7)
        self.assertLess(abs(network_ledger(g, p[0], 25)['energy_balance_error_w']), 1e-10)

    def test_longest_interval_not_last_activation(self):
        self.assertEqual(longest_interval([0, 1, 1, 0, 1, 0]), (1, 3))
        with self.assertRaises(ValueError):
            longest_interval([False, False])

    def test_tail_selection_excludes_off_state_and_drift_is_rejected(self):
        v = np.ones((1800, 16))
        i = np.full_like(v, .2)
        i[100:1500] = 3
        t = np.full_like(v, 30.)
        r = endpoint(v, i, t, np.full(16, 3.), 10)
        self.assertEqual((r['window_start_index'], r['window_end_exclusive']), (900, 1500))
        self.assertTrue(r['eligible'])
        t[:, 0] += np.arange(1800) / 10 * .01
        self.assertFalse(endpoint(v, i, t, np.full(16, 3.), 10)['eligible'])

    def test_power_uses_mean_of_product(self):
        v = np.tile([1., 2.], 600)[:, None] * np.ones((1, 16))
        i = v.copy()
        r = endpoint(v, i, np.full_like(v, 30.), np.full(16, 1.), 10)
        np.testing.assert_allclose(r['power_w'], 2.5)
        self.assertNotEqual(r['power_w'][0], v.mean() * i.mean())


if __name__ == '__main__':
    unittest.main()
