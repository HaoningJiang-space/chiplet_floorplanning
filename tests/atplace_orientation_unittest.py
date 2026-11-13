from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case as import_case
from atplace_orientation_repair import candidate_pool, prepare, repair, run_arm
from atplace_pin_geometry import make_thermal_case
from atplace_search import identities
from atplace_routing_screen import DEFAULT_RESOURCES
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.power import rasterize


class OrientationRepairTest(unittest.TestCase):
    def setUp(self):
        self.source = import_case('test', BLOCKS, POWER, NETS)
        self.source['chiplets'][1]['height_um'] = 3000
        self.poses = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=180),
                      dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=180)]
        self.plan = dict(gap_um=1000, resources=deepcopy(DEFAULT_RESOURCES), length_cap_m=1,
                         temperature_cap_c=100, resolution=8, thermal_budget_per_arm=1)

    def test_real_pin_repair_preserves_rectangular_bounds_and_input(self):
        original = deepcopy(self.poses)
        result = repair(self.source, self.poses, 1000)
        self.assertEqual(self.poses, original)
        self.assertEqual(identities(self.source, original, 1000)[1],
                         identities(self.source, result['placement'], 1000)[1])
        self.assertLess(result['metric']['total_pin_manhattan_m'], result['initial_metric']['total_pin_manhattan_m'])
        self.assertTrue(all(p['rotation_deg'] in (0, 180) for p in result['placement']))
        # Both fixture dies are rectangular: initial plus one alternative each.
        self.assertEqual(result['pin_evaluations'], 3)

    def test_square_tries_four_orientations_and_exact_tie_retains_incumbent(self):
        self.source['chiplets'][0]['height_um'] = self.source['chiplets'][0]['width_um']
        for net in self.source['nets']:
            for pin in net['pins']:
                pin['offset_x_um_decimal'] = pin['offset_y_um_decimal'] = '0'
        result = repair(self.source, self.poses, 1000)
        self.assertEqual(result['placement'], self.poses)
        self.assertEqual(result['pin_evaluations'], 5)  # 1+3+1

    def test_repaired_orientations_assemble_identical_physical_system(self):
        self.source['chiplets'][0]['height_um'] = self.source['chiplets'][0]['width_um']
        other = deepcopy(self.poses)
        other[0]['rotation_deg'], other[1]['rotation_deg'] = 90, 0
        systems = []
        for poses in (self.poses, other):
            case = parse_case(make_thermal_case(self.source, poses, 1000, resolution=8))
            power, _ = rasterize(case)
            systems.append(assemble_package(case, power))
        a, b, g, _, ids, _ = systems[0]
        c, d, h, _, jds, _ = systems[1]
        self.assertEqual((a-c).nnz, 0)
        np.testing.assert_array_equal(b, d)
        np.testing.assert_array_equal(g, h)
        np.testing.assert_array_equal(ids, jds)

    def test_fixed_pool_contains_only_axis_moves_and_repeats_seed_order(self):
        anchors = [dict(label='test', placement=self.poses)]
        pool, attempts = candidate_pool(self.source, anchors, 1000, 1000, 7)
        self.assertEqual(attempts, 8)
        self.assertEqual(candidate_pool(self.source, anchors, 1000, 1000, 7)[0], pool)
        self.assertGreater(len(pool), 0)
        for c in pool:
            changed = [i for i, p in enumerate(c['placement']) if p != self.poses[i]]
            self.assertEqual(len(changed), 1)
            self.assertEqual(abs(c['delta_um']), 1000)

    def test_routing_and_length_rejections_precede_warm_cache_and_solves(self):
        self.plan['candidates'] = [dict(candidate_id='candidate')]
        entry = prepare(self.source, self.poses, self.plan, False)
        def forbidden(data):
            self.fail('Rejected candidate reached heat solver')
        for kind in ('routing', 'length'):
            trial = deepcopy(entry)
            if kind == 'routing':
                trial['routing']['admitted'] = False
            else:
                trial['pin_length_m'] = 2
            result = run_arm(self.source, self.plan, 'test', [trial], [], {}, forbidden)
            self.assertEqual(result['effort']['new_thermal_queries'], 0)
            self.assertTrue(result['events'][0]['status'].startswith('rejected_'))

    def test_budget_counts_physical_queries_but_keeps_distinct_orientation_points(self):
        first = prepare(self.source, self.poses, self.plan, False)
        second = prepare(self.source, self.poses, self.plan, True)
        moved = deepcopy(self.poses)
        moved[0]['centre_x_um'] += 1000
        third = prepare(self.source, moved, self.plan, False)
        self.plan['candidates'] = [dict(candidate_id=str(i)) for i in range(3)]
        calls = []
        def solve(data):
            calls.append(data)
            return dict(peak_power_layer_c=80)
        result = run_arm(self.source, self.plan, 'test', [first, second, third], [], {}, solve)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['effort']['thermal_cache_hits'], 1)
        self.assertEqual(result['effort']['candidate_pin_evaluations'], 5)
        self.assertEqual(len(result['rows']), 2)
        self.assertNotEqual(result['rows'][0]['layout_key'], result['rows'][1]['layout_key'])
        self.assertEqual(result['events'][2]['status'], 'not_evaluated_budget')


if __name__ == '__main__':
    unittest.main()
