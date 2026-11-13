from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case
from atplace_pin_geometry import make_thermal_case
from atplace_routing_screen import DEFAULT_RESOURCES, RoutingScreenedEvaluator, screen_metric
from run_atplace_routing_boundary import variant_case, boundary_balance


def metric(pairs):
    return dict(nets=[dict(net_id=i, endpoints_um_decimal=[[str(v) for v in p] for p in pair])
                      for i, pair in enumerate(pairs)])


class RoutingScreenTest(unittest.TestCase):
    def test_cut_capacity_counts_both_directions_and_accepts_equality(self):
        # Two 1x1 bins; one H layer, one slot per edge. Two opposing nets
        # each need the same physical slot; they cannot cancel each other.
        r = dict(bin_um=1000, track_pitch_um=1000, horizontal_layers=1,
                 vertical_layers=1, access_pitch_um=100)
        pair = [(100, 200), (1800, 200)]
        a = screen_metric(metric([pair]), 2000, 1000, r)
        self.assertTrue(a['admitted'])
        self.assertEqual(a['worst_by_kind']['vertical_cut']['utilization'], 1)
        b = screen_metric(metric([pair, pair[::-1]]), 2000, 1000, r)
        self.assertFalse(b['admitted'])
        cut = b['worst_by_kind']['vertical_cut']
        self.assertEqual((cut['demand'], cut['capacity']), (2, 1))

    def test_bin_corner_has_only_two_escape_edges(self):
        r = dict(DEFAULT_RESOURCES, track_pitch_um=1000)
        pairs = [[(100, 100), (1100+i*10, 1100)] for i in range(3)]
        result = screen_metric(metric(pairs), 2000, 2000, r)
        corner = next(c for c in result['failed_conditions'] if c['kind'] == 'bin_escape')
        self.assertEqual((corner['location'], corner['demand'], corner['capacity']), ([0, 0], 3, 2))

    def test_internal_nets_use_access_but_no_escape(self):
        r = dict(DEFAULT_RESOURCES, access_pitch_um=1000)
        result = screen_metric(metric([[(100, 100), (200, 200)]]), 1000, 1000, r)
        self.assertFalse(result['admitted'])
        self.assertEqual(result['worst_by_kind']['bin_escape']['demand'], 0)
        self.assertEqual([c['kind'] for c in result['failed_conditions']], ['terminal_access'])

    def test_outer_boundary_and_invalid_pin(self):
        result = screen_metric(metric([[(0, 0), (2000, 1000)]]), 2000, 1000, DEFAULT_RESOURCES)
        self.assertTrue(result['admitted'])
        self.assertEqual(result['terminal_count'], 2)
        with self.assertRaises(ValueError):
            screen_metric(metric([[(0, 0), (2000.1, 1000)]]), 2000, 1000, DEFAULT_RESOURCES)

    def fixture(self):
        return parse_case('test', BLOCKS, POWER, NETS), [
            dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
            dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]

    def test_rejection_does_not_call_thermal_solver(self):
        source, poses = self.fixture()
        source['nets'].append(dict(deepcopy(source['nets'][0]), id=1))
        def forbidden(data):
            self.fail('Rejected layout reached the thermal solver')
        evaluator = RoutingScreenedEvaluator(source, 1000, forbidden, dict(DEFAULT_RESOURCES, access_pitch_um=1000))
        result = evaluator.evaluate(poses)
        self.assertEqual(result['status'], 'rejected_routing_necessary_condition')
        self.assertEqual(evaluator.solve_count, 0)
        self.assertEqual(evaluator.thermal_cache, {})

    def test_half_turn_rechecks_routing_before_thermal_cache(self):
        source, poses = self.fixture()
        calls = []
        def solve(data):
            calls.append(data)
            return dict(peak_c=80)
        evaluator = RoutingScreenedEvaluator(source, 1000, solve)
        a = evaluator.evaluate(poses)
        poses[0]['rotation_deg'] = 180
        b = evaluator.evaluate(poses)
        self.assertTrue(b['thermal_cache_hit'])
        self.assertEqual((len(calls), evaluator.routing_checks), (1, 2))
        self.assertNotEqual(a['routing']['worst_by_kind']['vertical_cut']['location'],
                            b['routing']['worst_by_kind']['vertical_cut']['location'])

    def test_boundary_variants_change_only_declared_parameter(self):
        source, poses = self.fixture()
        nominal = make_thermal_case(source, poses, 1000, resolution=8)
        original = deepcopy(nominal)
        for name, factor in (('half_h', .5), ('double_h', 2)):
            data = variant_case(nominal, name)
            self.assertEqual(data['thermal']['top_h_w_m2k'], factor*nominal['thermal']['top_h_w_m2k'])
            data['thermal']['top_h_w_m2k'] = nominal['thermal']['top_h_w_m2k']
            self.assertEqual(data, nominal)
        data = variant_case(nominal, 'tim_contact')
        tim = next(x for x in data['thermal']['layers'] if x['id'] == 'tim')
        self.assertEqual(tim.pop('contact_resistance_above_m2k_w'), 5e-6)
        self.assertEqual(data, nominal)
        self.assertEqual(nominal, original)

    def test_declared_top_area_and_global_balance_units(self):
        source, poses = self.fixture()
        nominal = make_thermal_case(source, poses, 1000, resolution=8)
        for name, resistance in ((None, .009), ('half_h', .018), ('double_h', .0045), ('tim_contact', .009)):
            data = nominal if name is None else variant_case(nominal, name)
            balance = boundary_balance(data)
            self.assertEqual(balance['top_area_m2'], .04)
            self.assertAlmostEqual(balance['convection_resistance_k_w'], resistance)
            self.assertAlmostEqual(balance['surface_mean_c'], 45+2.5*resistance)


if __name__ == '__main__':
    unittest.main()
