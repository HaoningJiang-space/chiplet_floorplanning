import unittest

import numpy as np

from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.relocation import ConnectionCost, landing_bank, rectangle_resistance, select_landing


class RelocationTests(unittest.TestCase):
    def test_square_patch_centre_and_far_field(self):
        width = 4.0
        centre = rectangle_resistance([0., 0.], [4000., 4000.])
        self.assertAlmostEqual(centre, 4 * np.arcsinh(1) / (2 * np.pi * .4 * width))
        self.assertAlmostEqual(rectangle_resistance([100000., 0], [1000., 1000.]),
                               1 / (2 * np.pi * .4 * 100), places=6)

    def test_finite_landings_match_full_field_and_rotated_pins(self):
        p = Problem("test", ("A", "B", "C"), np.array([[2000., 1000.], [1000., 1000.], [1000., 1000.]]),
                    np.array([10., 6., 1.]), (7000., 7000.), np.array([[0, 1], [2, 0], [0, 0]]),
                    np.array([[[100., 200.], [0., 20.]], [[-50., 0.], [0., 150.]], [[20., 0.], [0., 80.]]]))
        l = Layout(np.array([[1500., 2000.], [3500., 2000.], [3500., 5000.]]), np.array([90, 0, 180]))
        cost = ConnectionCost(p, l)
        bank, field = landing_bank(p, p, l, cost)
        self.assertTrue(any(len(x.chips) == 2 for x in bank))
        for point in bank:
            geometry = point.apply(l)
            self.assertAlmostEqual(point.cost, pin_manhattan_um(p, geometry).sum() / 1e6)
            self.assertAlmostEqual(point.rise_k, field.rises(geometry.centre_um).max())
        chosen = select_landing(bank, cost.initial)
        self.assertLessEqual(chosen.cost, cost.initial + 1e-9)
