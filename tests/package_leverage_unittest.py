from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from package_leverage import leverage, verdict  # noqa: E402
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import solve_cold_plate  # noqa: E402


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


class ColdPlateTest(unittest.TestCase):
    def setUp(self):
        self.problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        self.plate = dict(cold_plate_h_w_m2k=5000.)

    def data(self, centres):
        return thermal_case_data(self.problem, Layout(np.array(centres), np.array([0, 0])), 0., package=self.plate)

    def test_fast_flow_reduces_to_the_fixed_coolant_solve(self):
        data = self.data([[2000., 1000.], [5500., 1000.]])
        fast = solve_cold_plate(data, 1e6, '+x')
        self.assertAlmostEqual(fast['peak_power_layer_c'], solve_peak(data)['peak_power_layer_c'], places=6)

    def test_slow_flow_heats_downstream_and_mirrors_with_the_direction(self):
        # The fixture carrier is symmetric about x; mirror the layout and reverse the flow.
        width = self.problem.carrier_um[0]
        left = self.data([[2000., 1000.], [5500., 1000.]])
        mirrored = self.data([[width - 2000., 1000.], [width - 5500., 1000.]])
        flow = 2e-4
        a, b = solve_cold_plate(left, flow, '+x'), solve_cold_plate(mirrored, flow, '-x')
        self.assertAlmostEqual(a['peak_power_layer_c'], b['peak_power_layer_c'], places=6)
        self.assertAlmostEqual(a['outlet_rise_k'], a['source_power_w']/(flow*4186.))
        self.assertGreater(a['peak_power_layer_c'], solve_cold_plate(left, 1e6, '+x')['peak_power_layer_c'])
        self.assertNotAlmostEqual(a['peak_power_layer_c'], solve_cold_plate(left, flow, '-x')['peak_power_layer_c'],
                                  places=3)
