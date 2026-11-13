from copy import deepcopy
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_slack import encode, decode, slack_crossover
from atplace_search import CostLimit, Space
from atplace_pin_geometry import placement_geometry
from atplace_slack_search import run_policy
from import_atplace_cases import parse_case as import_case
from atplace_import_unittest import BLOCKS, POWER, NETS


class SlackRepresentationTest(unittest.TestCase):
    def setUp(self):
        self.source = dict(interposer_width_um=15000, interposer_height_um=10000,
            chiplets=[dict(name='a', width_um=3000, height_um=2000),
                      dict(name='b', width_um=2000, height_um=4000)])
        self.a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=90),
                  dict(chiplet='b', centre_x_um=11000, centre_y_um=5000, rotation_deg=270)]
        self.b = [dict(chiplet='a', centre_x_um=11000, centre_y_um=3000, rotation_deg=90),
                  dict(chiplet='b', centre_x_um=3000, centre_y_um=5000, rotation_deg=270)]

    def test_round_trip_preserves_noncompact_positions_and_rotations(self):
        for p in (self.a, self.b):
            before = deepcopy((self.source, p))
            g = encode(self.source, p, 1000, 1000)
            self.assertEqual(decode(g, g['slacks']), p)
            self.assertEqual((self.source, p), before)

    def test_all_extreme_slacks_respect_outline_and_half_grid_dimensions(self):
        for p in (self.a, self.b):
            g = encode(self.source, p, 1000, 1000)
            for mask in range(16):
                slack = [[[int(bool(mask & (1 << (2*i+axis)))), 1] for axis in (0, 1)] for i in range(2)]
                q = decode(g, slack)
                placement_geometry(self.source, q, 1000)
                self.assertEqual([x['rotation_deg'] for x in q], [90, 270])

    def test_reconstruction_can_escape_cross_parent_coordinate_conflict(self):
        # Absolute mixing puts both dies at x=3 or x=11, violating the gap.
        for p in ([self.a[0], self.b[1]], [self.b[0], self.a[1]]):
            with self.assertRaises(ValueError):
                placement_geometry(self.source, p, 1000)
        class FixedDraw:
            def randrange(self, *args):
                return 0 if len(args) == 1 else 1
        space = Space(self.source, 1000, 1000, 3)
        receipt = {}
        p = slack_crossover(space, self.a, self.b, FixedDraw(), receipt)
        placement_geometry(self.source, p, 1000)
        self.assertNotIn(p, (self.a, self.b))
        self.assertEqual(receipt['selection'], 'novel_reconstruction')
        self.assertEqual(space.checks, 3)
        self.assertGreater(receipt['new_coordinate_genes'], 0)

    def test_identical_parents_and_exhausted_budget(self):
        space = Space(self.source, 1000, 1000, 3)
        receipt = {}
        self.assertEqual(slack_crossover(space, self.a, self.a, random.Random(1), receipt), self.a)
        self.assertEqual(receipt['selection'], 'parent_reconstruction')
        receipt = {}
        with self.assertRaises(CostLimit):
            slack_crossover(space, self.a, self.b, random.Random(1), receipt)
        self.assertNotIn('placement', receipt)

    def test_invalid_coordinates_or_slack_are_not_silently_clamped(self):
        p = deepcopy(self.a)
        p[0]['centre_x_um'] += 1
        with self.assertRaisesRegex(ValueError, 'grid'):
            encode(self.source, p, 1000, 1000)
        g = encode(self.source, self.a, 1000, 1000)
        bad = deepcopy(g['slacks'])
        bad[0][0] = [3, 2]
        with self.assertRaisesRegex(ValueError, 'slack'):
            decode(g, bad)

    def test_search_budget_and_geometry_with_saved_response_style_oracle(self):
        source = import_case('test', BLOCKS, POWER, NETS)
        a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
             dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        b = deepcopy(a)
        b[0]['centre_y_um'] += 1000
        plan = dict(seed=2026111200, gap_um=1000, grid_um=1000, population=2,
            proposal_cap=200, candidate_check_cap=100000, pin_call_cap=1000, thermal_budget=4,
            length_cap_m=.0072, temperature_cap_c=80., initialization=dict(placements=[a, b],
            construction_attempts=1, candidate_checks=0, elapsed_seconds=0.))
        result = run_policy(source, plan, lambda d: dict(numerical_admission_passed=True, peak_power_layer_c=80.))
        self.assertEqual(result['status'], 'complete_thermal_budget')
        self.assertEqual(result['effort']['thermal_queries'], 4)
        self.assertEqual(result['effort']['illegal_proposals'], 0)
        self.assertGreater(result['effort']['crossover_geometry_checks'], 0)
        for row in result['rows']:
            placement_geometry(source, row['placement'], 1000)


if __name__ == '__main__':
    unittest.main()
