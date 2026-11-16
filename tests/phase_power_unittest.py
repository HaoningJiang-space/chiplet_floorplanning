from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from chiplet_floorplanning.placement import is_legal  # noqa: E402
from phase_power import GAP_UM, binding, die_temperatures, h100_problem, hand_layout  # noqa: E402


class PhasePowerTest(unittest.TestCase):
    def test_hand_layout_is_legal_with_the_ihp_spacing_and_keeps_hbm_beside_the_gpu(self):
        problem, layout = h100_problem('prefill'), hand_layout()
        self.assertTrue(is_legal(problem, layout, GAP_UM))
        self.assertFalse(is_legal(problem, layout, GAP_UM + 1))   # spacing is exactly the rule
        self.assertAlmostEqual(problem.power_w.sum(), 540 + 5*22)

    def test_stronger_cooling_lowers_every_working_die(self):
        problem, layout = h100_problem('decode'), hand_layout()
        weak, strong = die_temperatures(problem, layout, 2000.0), die_temperatures(problem, layout, 8000.0)
        self.assertTrue((strong[:-1] < weak[:-1]).all())

    def test_binding_ignores_the_dummy_and_uses_each_limit(self):
        k, over = binding(np.array([90., 80., 80., 80., 80., 80., 200.]), 95., 85.)
        self.assertEqual(k, 0)                       # GPU -5 K beats HBM -5 K tie on order; dummy excluded
        k, _ = binding(np.array([90., 88., 80., 80., 80., 80., 200.]), 95., 85.)
        self.assertEqual(k, 1)


if __name__ == '__main__':
    unittest.main()
