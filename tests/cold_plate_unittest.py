from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data  # noqa: E402
from chiplet_floorplanning.placement.thermal import solve_cold_plate  # noqa: E402


class DefaultPackageTest(unittest.TestCase):
    def test_air_sink_is_unchanged_and_the_cold_plate_replaces_it(self):
        problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        air = thermal_case_data(problem, layout, 0.)
        self.assertEqual(solve_peak(air)['peak_power_layer_c'], 48.38459530567995)  # recipe before the cold plate
        plate = thermal_case_data(problem, layout, 0., cold_plate_h_w_m2k=5000.)
        self.assertEqual([l['id'] for l in plate['thermal']['layers']][-2:], ['spreader', 'cold_plate'])
        self.assertEqual(plate['thermal']['top_h_w_m2k'], 5000.)


class ColdPlateTest(unittest.TestCase):
    def setUp(self):
        self.problem = Problem.from_imported(import_case('fixture', BLOCKS, POWER, NETS))

    def data(self, centres):
        return thermal_case_data(self.problem, Layout(np.array(centres), np.array([0, 0])), 0., cold_plate_h_w_m2k=5000.)

    def test_fast_flow_reduces_to_the_fixed_coolant_solve(self):
        data = self.data([[2000., 1000.], [5500., 1000.]])
        fast = solve_cold_plate(data, 1e6, '+x')
        self.assertAlmostEqual(fast[0]['peak_power_layer_c'], solve_peak(data)['peak_power_layer_c'], places=6)

    def test_slow_flow_heats_downstream_and_mirrors_with_the_direction(self):
        # The fixture carrier is symmetric about x; mirror the layout and reverse the flow.
        width = self.problem.carrier_um[0]
        left = self.data([[2000., 1000.], [5500., 1000.]])
        mirrored = self.data([[width - 2000., 1000.], [width - 5500., 1000.]])
        flow = 2e-4
        a, b = solve_cold_plate(left, flow, '+x'), solve_cold_plate(mirrored, flow, '-x')
        self.assertAlmostEqual(a[0]['peak_power_layer_c'], b[0]['peak_power_layer_c'], places=6)
        self.assertAlmostEqual(a[0]['outlet_rise_k'], a[0]['source_power_w']/(flow*4186.))
        self.assertGreater(a[0]['peak_power_layer_c'], solve_cold_plate(left, 1e6, '+x')[0]['peak_power_layer_c'])
        self.assertNotAlmostEqual(a[0]['peak_power_layer_c'], solve_cold_plate(left, flow, '-x')[0]['peak_power_layer_c'],
                                  places=3)
