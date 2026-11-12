import copy
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.linalg import expm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.ttc_observation import propagate, simulate, raw_metrics, OPERATORS
from validation.measured_transient import simulate as previous_simulate
from validation.ttc_geometry import check_geometry


class TTCObservationTest(unittest.TestCase):
    def test_scalar_end_and_exact_average_including_last_interval(self):
        for dt in (1e-6, .1, 100.):
            g, c, p, initial = 2., 3., 5., 1.
            rate, steady = g/c, p/g
            x = rate*dt
            expected_end = steady+(initial-steady)*np.exp(-x)
            expected_average = steady+(initial-steady)*(-np.expm1(-x)/x)
            for operator, expected in [('begin', initial), ('end', expected_end), ('average', expected_average)]:
                y, audit = propagate([[g]], [c], [[p]], [initial], dt, operator, True)
                self.assertAlmostEqual(y[0, 0], expected, places=12)
                self.assertAlmostEqual(audit['input_energy_j'], p*dt)
                self.assertTrue(audit['numerical_energy_screen'])

    def test_independent_exponential_with_integrated_state(self):
        g = np.array([[3., -1.], [-1., 2.]])
        c = np.array([.02, 7.])
        p = np.array([[1., 0.], [0., 4.], [2., 1.]])
        initial = np.array([2., 3.])
        # State [T, constant power, integral(T)]. This independent reference
        # has no eigenmode decomposition or observation-code recurrence.
        aug = np.zeros((6, 6))
        aug[:2, :2] = -g/c[:, None]
        aug[:2, 2:4] = np.diag(1/c)
        aug[4:, :2] = np.eye(2)
        transition = expm(aug*.1)
        state = initial.copy()
        expected = {key: [] for key in OPERATORS}
        for row in p:
            expected['begin'].append(state.copy())
            evolved = transition @ np.r_[state, row, 0., 0.]
            state = evolved[:2]
            expected['end'].append(state.copy())
            expected['average'].append(evolved[4:]/.1)
        for operator in OPERATORS:
            result, audit = propagate(g, c, p, initial, .1, operator, True)
            np.testing.assert_allclose(result, expected[operator], atol=1e-12)
            self.assertEqual(audit['interval_count'], 3)
            self.assertLess(abs(audit['energy_balance_error_j']), 1e-12)
            self.assertLess(audit['max_interval_energy_error_j'], 1e-12)

    def test_begin_preserves_previous_predictions(self):
        params = np.log([.1, .2, .8, .03, 10.])
        p = np.zeros((31, 16)); p[:12, 0] = 3; p[22:, 7] = 1
        initial = np.linspace(1, 2, 16)
        old, _ = previous_simulate(params, p, initial)
        new, _ = simulate(params, p, initial, 'begin')
        np.testing.assert_allclose(new, old, atol=1e-12)

    def test_passive_cooling_and_invalid_inputs(self):
        for operator in OPERATORS:
            y, _ = propagate([[2., -1.], [-1., 2.]], [1., 3.], np.zeros((50, 2)), [3., 3.], .1, operator)
            self.assertGreaterEqual(y.min(), 0)
            self.assertLessEqual(y.max(), 3.+1e-12)
        for g in ([[1., 1.], [1., 2.]], [[1., -2.], [-2., 3.]]):
            with self.assertRaises(ValueError):
                propagate(g, [1., 1.], [[1., 1.]], [0., 0.], .1)
        with self.assertRaises(ValueError):
            propagate([[1.]], [1.], [[1.]], [0.], float('nan'))

    def test_unsmoothed_peak_is_retained(self):
        error = np.zeros((100, 16)); error[50, 7] = 28.
        metrics = raw_metrics(error)
        self.assertEqual(metrics['max_abs_error_k'], 28.)
        self.assertAlmostEqual(metrics['mae_k'], 28/1600)
        self.assertAlmostEqual(metrics['rmse_k'], 28/40)

    def test_geometry_catches_missing_half_and_rotated_input(self):
        sensors = [[(r+.5)*2560, (c+.5)*2560] for r in range(4) for c in range(4)]
        heaters = []
        for i, (x, y) in enumerate(sensors):
            for offset in (-1000., 100.):
                heaters.append(dict(power_index=i, power_fraction=.5,
                                    x_um=x-1000., y_um=y+offset, width_um=2000., height_um=900.))
        self.assertTrue(check_geometry(heaters, sensors, 10240)['geometry_conservation_screen'])
        with self.assertRaisesRegex(ValueError, 'conservative'):
            check_geometry(heaters[:-1], sensors, 10240)
        wrong = copy.deepcopy(heaters)
        for h in wrong:
            if h['power_index'] in (0, 1):
                h['power_index'] = 1-h['power_index']
        with self.assertRaisesRegex(ValueError, 'association'):
            check_geometry(wrong, sensors, 10240)


if __name__ == '__main__':
    unittest.main()
