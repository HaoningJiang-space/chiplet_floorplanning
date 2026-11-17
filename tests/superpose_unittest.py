from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from superpose_check import prefix_regret  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from chiplet_floorplanning.placement.superpose import SuperposedModel  # noqa: E402
from chiplet_floorplanning.placement.thermal import die_peaks_c, solve, thermal_case_data  # noqa: E402


class SuperposedModelTest(unittest.TestCase):
    def test_lone_die_and_quarter_turn_symmetry(self):
        p = Problem('one', ('a', 'b'), np.array([[8000., 4000.], [4000., 4000.]]), np.array([10., 0.]), (40000., 40000.),
                    np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        model = SuperposedModel.calibrate(p, resolution=32)
        far = Layout(np.array([[20000., 20000.], [36000., 36000.]]), np.zeros(2, int))
        _, rise, edges = solve(thermal_case_data(p, far, 0, 32))
        fv = die_peaks_c(p, far, rise, edges)
        self.assertLess(abs(model.die_peaks_c(p, far)[0] - fv[0]), 0.5)    # the self term is the calibration itself
        # A quarter turn of the source turns its field: the observer east of a turned source sees what an observer
        # north of an unturned source sees.
        east = model.die_peaks_c(p, Layout(np.array([[20000., 20000.], [29000., 20000.]]), np.array([90, 0])))[1]
        north = model.die_peaks_c(p, Layout(np.array([[20000., 20000.], [20000., 29000.]]), np.array([0, 0])))[1]
        self.assertAlmostEqual(east, north, places=2)

    def test_prefix_regret(self):
        self.assertEqual(prefix_regret(np.array([1., 2., 3.]), np.array([1., 2., 3.])), 0.0)
        # Prefix 2 picks the first (FV 2 vs best 1); prefix 3 picks the last (FV 3 vs best 1).
        self.assertAlmostEqual(prefix_regret(np.array([1., 2., 0.5]), np.array([2., 1., 3.])), 2.0)


if __name__ == '__main__':
    unittest.main()
