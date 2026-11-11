import sys
from pathlib import Path
import unittest

import numpy as np
from scipy.linalg import expm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.measured_transient import matrices, simulate
from validation.measured_thermal import predict


class MeasuredTransientTest(unittest.TestCase):
    def test_independent_augmented_matrix_exponential_and_energy(self):
        params = np.log([.1, .2, .8, .03, 10.])
        p = np.zeros((21, 16))
        p[:7, 0] = 2
        p[7:15, 15] = 3
        initial = np.arange(16) * .1
        y, audit = simulate(params, p, initial, ledger=True)
        g, c, _ = matrices(params)
        augmented = np.zeros((34, 34))
        augmented[:17, :17] = -g / c[:, None]
        augmented[:17, 17:] = np.diag(1 / c)
        transition = expm(augmented * .1)
        reference = [np.r_[initial, audit['initial_bath_rise_k']]]
        for power in p[:-1]:
            reference.append((transition @ np.r_[reference[-1], power, 0])[:17])
        np.testing.assert_allclose(y, reference, atol=1e-10, rtol=1e-10)
        self.assertTrue(audit['numerical_energy_screen'])
        self.assertLess(abs(audit['energy_balance_error_j']), 1e-10)

    def test_equilibrium_is_stationary_and_passive_cooling_has_no_overshoot(self):
        params = np.log([.1, .2, .8, .03, 1.])
        p = np.ones((100, 16))
        steady = predict(params[:3], p[0])
        y, _ = simulate(params, p, steady)
        np.testing.assert_allclose(y[:, :16], np.broadcast_to(steady, (100, 16)), atol=1e-10)
        cooled, audit = simulate(params, np.zeros_like(p), np.full(16, 20.), alternative_initial=True, ledger=True)
        self.assertTrue(np.all(cooled >= 0))
        self.assertLessEqual(float(cooled.max()), 20. + 1e-10)
        self.assertTrue(audit['numerical_energy_screen'])


if __name__ == '__main__':
    unittest.main()
