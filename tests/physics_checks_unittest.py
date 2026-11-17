from pathlib import Path
import sys
import unittest
import unittest.mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from physics_checks import (R_MM, decay_verdict, fit_lambda, g_model, lambda_theory_mm,  # noqa: E402
                            predicted_area_rise, proxy_peak_c)


class PhysicsChecksTest(unittest.TestCase):
    def test_fit_recovers_a_known_decay_length(self):
        lam, c = fit_lambda(R_MM, g_model(R_MM, 21.0, 1.3))
        self.assertAlmostEqual(lam, 21.0, places=6)
        self.assertAlmostEqual(c, 1.3, places=6)
        self.assertAlmostEqual(lambda_theory_mm(1/(.1*.06**2)), 33.73, places=1)

    def test_decay_verdict(self):
        rows = lambda fits: [dict(h=h, lambda_fit_mm=f, lambda_theory_mm=lambda_theory_mm(h))
                             for h, f in zip((1500., 2778., 5000., 15000., 50000.), fits)]
        self.assertEqual(decay_verdict(rows([lambda_theory_mm(h) for h in (1500., 2778., 5000., 15000., 50000.)]))[0],
                         'holds')
        self.assertEqual(decay_verdict(rows([30., 30., 29.9, 29.8, 29.7]))[0], 'fails')

    def test_proxy_falls_with_spacing_and_area_prediction_is_positive(self):
        problem = Problem('p', ('a', 'b'), np.array([[5000., 5000.]]*2), np.array([10., 10.]), (60000., 20000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        s = np.array([2.0, 2.0])
        near = Layout(np.array([[10000., 10000.], [16000., 10000.]]), np.zeros(2, int))
        far = Layout(np.array([[10000., 10000.], [50000., 10000.]]), np.zeros(2, int))
        self.assertGreater(proxy_peak_c(problem, near, s, 20., 1.), proxy_peak_c(problem, far, s, 20., 1.))
        self.assertAlmostEqual(proxy_peak_c(problem, far, s, 20., 1.), 45 + 20 + 10*float(g_model(np.array(40.), 20., 1.)))
        self.assertGreater(predicted_area_rise(problem, 20., 1.), 0)

    def test_results_with_numpy_scalars_are_written(self):
        # The first run printed every result but died writing JSON: numpy ints are not JSON types.
        import json
        import tempfile
        from types import SimpleNamespace
        import physics_checks
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(physics_checks, 'decay', lambda h: g_model(R_MM, 30., 1.)):
            out = Path(d)/'decay.json'
            physics_checks.cmd_decay(SimpleNamespace(output=out))
            self.assertIn(json.loads(out.read_text())['verdict'], ('holds', 'partial', 'fails'))


if __name__ == '__main__':
    unittest.main()
