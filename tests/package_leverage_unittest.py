from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from package_leverage import leverage, verdict  # noqa: E402
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data  # noqa: E402


class PackageLeverageTest(unittest.TestCase):
    def test_uniform_offset_neither_interacts_nor_changes_the_best_layout(self):
        length, base = [10., 11., 12.5, 20.], np.array([100., 98., 97., 95.])
        rows = leverage(length, dict(base=base, hot=base + 7.))
        self.assertEqual(rows['hot']['package_shift_k'], 7.)
        self.assertEqual((rows['hot']['lever_k'], rows['hot']['best']), (3., 2))  # layout 3 lies beyond the cap
        self.assertFalse(rows['hot']['interacting'] or rows['hot']['best_changed'])
        self.assertEqual(verdict([rows]), 'degenerate')

    def test_lever_that_collapses_and_new_best_layout_are_reported(self):
        length, base = [10., 11., 12.], np.array([100., 98., 97.])
        rows = leverage(length, dict(base=base, flat=np.array([105., 104.9, 104.95]),
                                     swap=np.array([100., 96., 97.])))
        self.assertTrue(rows['flat']['interacting'])
        self.assertAlmostEqual(rows['flat']['relative_lever_change'], (0.1 - 3)/3)
        self.assertTrue(rows['swap']['best_changed'])
        self.assertEqual(verdict([rows]*2), 'uncertain')
        self.assertEqual(verdict([rows]*3), 'worthwhile')

    def test_default_package_reproduces_the_frozen_recipe_and_rejects_unknown_knobs(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        default = thermal_case_data(problem, layout, 0.)
        self.assertEqual(default, thermal_case_data(problem, layout, 0., package=dict(tim_k=4.)))
        worse = solve_peak(thermal_case_data(problem, layout, 0., package=dict(tim_k=1.)))
        self.assertGreater(worse['peak_power_layer_c'], solve_peak(default)['peak_power_layer_c'])
        with self.assertRaises(ValueError):
            thermal_case_data(problem, layout, 0., package=dict(lid=True))


if __name__ == '__main__':
    unittest.main()
