from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case as import_case
from atplace_pin_geometry import pin_objective, make_thermal_case, UniformDiePinEvaluator
from chiplet_floorplanning.model import parse_case


class AtplacePinGeometryTest(unittest.TestCase):
    def setUp(self):
        self.case = import_case('test', BLOCKS, POWER, NETS)
        self.poses = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
                      dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]

    def test_hand_computed_orientations_not_centre_proxy(self):
        # a local offset=(1000,-200), b=(-500,500); b global=(7500,6500).
        for angle, expected_um in ((0, 7200), (90, 6800), (180, 8800), (270, 9200)):
            self.poses[0]['rotation_deg'] = angle
            value = pin_objective(self.case, self.poses, 1000)
            self.assertEqual(Decimal(value['total_pin_manhattan_um_decimal']), expected_um)
            self.assertEqual(value['total_centre_manhattan_mm'], 8)

    def test_translation_and_net_multiplicity(self):
        base = pin_objective(self.case, self.poses, 1000)
        for p in self.poses:
            p['centre_x_um'] += 100
            p['centre_y_um'] += 200
        self.assertEqual(pin_objective(self.case, self.poses, 1000)['total_pin_manhattan_mm'],
                         base['total_pin_manhattan_mm'])
        self.case['nets'].append(dict(deepcopy(self.case['nets'][0]), id=1))
        self.assertEqual(pin_objective(self.case, self.poses, 1000)['total_pin_manhattan_mm'],
                         2*base['total_pin_manhattan_mm'])

    def test_source_domain_and_gap_are_checked(self):
        for field, value in (('centre_x_um', 9000), ('centre_x_um', 1000), ('rotation_deg', 45)):
            poses = deepcopy(self.poses)
            poses[0][field] = value
            with self.assertRaises(ValueError):
                pin_objective(self.case, poses, 1000)
        with self.assertRaises(ValueError):
            pin_objective(self.case, self.poses[:1], 1000)
        self.poses[0].update(centre_x_um=6000, centre_y_um=5000)
        with self.assertRaises(ValueError):
            pin_objective(self.case, self.poses, 1000)

    def test_thermal_adapter_preserves_power_and_transformed_ports(self):
        self.poses[0]['rotation_deg'] = 90
        data = make_thermal_case(self.case, self.poses, 1000, resolution=8)
        case = parse_case(data)
        self.assertEqual(sum(b.power_w for d in case.dies for b in d.blocks), 2.5)
        a, b = case.dies
        # Source carrier is centred within the 200 mm package: offset=95 mm.
        self.assertAlmostEqual(a.point(*a.ports['n0_0'])[0], 98.2)
        self.assertAlmostEqual(a.point(*a.ports['n0_0'])[1], 99)
        self.assertEqual(b.point(*b.ports['n0_1']), (102.5, 101.5))
        self.assertEqual(case.links, ())

    def test_only_temperature_is_reused_across_180_degree_states(self):
        calls = []
        def solve(data):
            calls.append(data)
            return {'peak_c': 80.0}
        ev = UniformDiePinEvaluator(self.case, 1000, solve, resolution=8)
        a = ev.evaluate(self.poses)
        self.poses[0]['rotation_deg'] = 180
        b = ev.evaluate(self.poses)
        self.assertNotEqual(a['layout_key'], b['layout_key'])
        self.assertFalse(a['thermal_cache_hit'])
        self.assertTrue(b['thermal_cache_hit'])
        self.assertEqual((ev.solve_count, ev.cache_hits, len(calls)), (1, 1, 1))
        self.assertEqual(a['thermal_result'], b['thermal_result'])
        self.assertEqual(a['metric']['total_pin_manhattan_mm'], 7.2)
        self.assertEqual(b['metric']['total_pin_manhattan_mm'], 8.8)
        self.poses[0]['rotation_deg'] = 90
        ev.evaluate(self.poses)
        # This fixture's non-square die changes its physical bounds at 90 degrees.
        self.assertEqual(ev.solve_count, 2)


if __name__ == '__main__':
    unittest.main()
