from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from thermal_kernel_screen import fv_peak_c, kernels, predicted_peak_c, sample_points_um, verdict  # noqa: E402


class ThermalKernelScreenTest(unittest.TestCase):
    def test_one_die_off_centre_matches_the_fv_peak(self):
        # A lone die: superposition is exact up to the translation of its kernel and the 5x5 sampling.
        problem = Problem('one', ('a',), np.array([[8000., 5000.]]), np.array([20.]), (40000., 30000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        table = kernels(problem, 0)
        for centre, turn in (((12000., 20000.), 0), ((25000., 9000.), 90)):
            layout = Layout(np.array([centre]), np.array([turn]))
            self.assertAlmostEqual(predicted_peak_c(problem, layout, table), fv_peak_c((problem, layout, 0)), delta=0.3)

    def test_sample_points_follow_rotation_and_verdict_counts(self):
        problem = Problem.from_imported(synthetic_case(random.Random(3), chips=2, nets=4))
        layout = Layout(np.array([[5000., 5000.], [20000., 5000.]]), np.array([0, 90]))
        pts = sample_points_um(problem, layout)
        w, h = problem.size_um[1]
        np.testing.assert_allclose(np.ptp(pts[1], axis=0), 0.8*np.array([h, w]))
        rows = lambda ok: {str(k): dict(usable=k < ok) for k in range(7)}
        self.assertEqual((verdict(rows(6)), verdict(rows(3)), verdict(rows(4))), ('usable', 'not_usable', 'partial'))


if __name__ == '__main__':
    unittest.main()
