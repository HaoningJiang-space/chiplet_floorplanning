from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from thermal_kernel_screen import (anchor_peak_c, anchor_table, bracket, floor_peak_c, fv_peak_c,  # noqa: E402
                                   sample_points_um, verdict)

SERIAL = SimpleNamespace(map=map)


class ThermalKernelScreenTest(unittest.TestCase):
    def test_one_die_between_anchors_matches_the_fv_peak(self):
        problem = Problem('one', ('a',), np.array([[8000., 5000.]]), np.array([20.]), (40000., 30000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        table = anchor_table(problem, 0, SERIAL)
        for centre, turn in (((12000., 20000.), 0), ((25000., 9000.), 90)):
            layout = Layout(np.array([centre]), np.array([turn]))
            fv = fv_peak_c((problem, layout, 0))
            self.assertAlmostEqual(floor_peak_c(problem, layout, 0, SERIAL), fv, delta=0.3)   # exact up to sampling
            self.assertAlmostEqual(anchor_peak_c(problem, layout, table), fv, delta=0.5)

    def test_far_apart_dies_stay_defined_and_the_anchor_kernel_tracks_the_floor(self):
        # The first screen's translated kernels left the carrier here and returned NaN.
        problem = Problem('two', ('a', 'b'), np.array([[6000., 6000.], [4000., 4000.]]), np.array([30., 10.]),
                          (60000., 20000.), np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        layout = Layout(np.array([[4000., 4000.], [56000., 17000.]]), np.array([0, 90]))
        anchor = anchor_peak_c(problem, layout, anchor_table(problem, 0, SERIAL))
        floor = floor_peak_c(problem, layout, 0, SERIAL)
        self.assertTrue(np.isfinite(anchor) and np.isfinite(floor))
        self.assertAlmostEqual(anchor, floor, delta=0.5)
        self.assertAlmostEqual(floor, fv_peak_c((problem, layout, 0)), delta=1.0)

    def test_sample_points_brackets_and_verdict(self):
        problem = Problem.from_imported(synthetic_case(random.Random(3), chips=2, nets=4))
        layout = Layout(np.array([[5000., 5000.], [20000., 5000.]]), np.array([0, 90]))
        w, h = problem.size_um[1]
        np.testing.assert_allclose(np.ptp(sample_points_um(problem, layout)[1], axis=0), 0.8*np.array([h, w]))
        self.assertEqual(bracket(np.array([0., 10., 20.]), 15.), [(1, 0.5), (2, 0.5)])
        self.assertEqual(bracket(np.array([5., 5.]), 5.), [(0, 1.0)])
        rows = lambda ok: {str(k): dict(usable=k < ok) for k in range(7)}
        self.assertEqual((verdict(rows(6)), verdict(rows(3)), verdict(rows(4))), ('usable', 'not_usable', 'partial'))


if __name__ == '__main__':
    unittest.main()
