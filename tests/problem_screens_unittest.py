from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um, sample_legal  # noqa: E402
from problem_screens import box_gap_um, saving  # noqa: E402


class ProblemScreensTest(unittest.TestCase):
    def test_box_gap_is_the_free_phy_length(self):
        pins = np.array([[0, 1], [0, 2]])
        offsets = np.array([[[-1000., 0.], [1000., 0.]], [[0., 0.], [0., 0.]]])   # pins on the far edges
        problem = Problem('p', ('a', 'b', 'c'), np.array([[2000., 2000.]]*3), np.ones(3), (20000., 20000.), pins, offsets)
        layout = Layout(np.array([[3000., 3000.], [5000., 3000.], [9000., 7000.]]), np.zeros(3, int))
        # a and b touch; the boxes of a and c are 4 mm apart in x and 2 mm in y
        np.testing.assert_allclose(box_gap_um(problem, layout), [0., 4000. + 2000.])
        np.testing.assert_allclose(pin_manhattan_um(problem, layout), [4000., 6000. + 4000.])
        self.assertAlmostEqual(saving(problem, layout), 1 - 6000./14000.)

    def test_free_phy_never_lengthens_a_net(self):
        problem = Problem.from_imported(synthetic_case(random.Random(11), chips=5, nets=60))
        rng = np.random.default_rng(3)
        for _ in range(5):
            layout = sample_legal(problem, 500, rng)
            self.assertTrue((box_gap_um(problem, layout) <= pin_manhattan_um(problem, layout) + 1e-6).all())
            self.assertGreaterEqual(saving(problem, layout), 0)


if __name__ == '__main__':
    unittest.main()
