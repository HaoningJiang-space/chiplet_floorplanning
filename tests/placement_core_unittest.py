from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case as import_case
from chiplet_floorplanning.placement import (Layout, Problem, is_legal, pin_manhattan_um, solve_peak,
                                             thermal_case_data, violations)

# Legacy equivalence (519 recorded Case1 layouts, max |dT| 1.6e-8 K) is recorded in commit f1df9fd.


def synthetic_case(rng, chips=5, nets=200):
    sizes = [(rng.randint(2, 8)*1000, rng.randint(2, 8)*1000) for _ in range(chips)]
    blocks = ''.join(f'c{i} hardrectilinear 4 (0, 0) (0, {h}) ({w}, {h}) ({w}, 0)\n' for i, (w, h) in enumerate(sizes))
    header = (f'NumSoftRectangularBlocks : 0\nNumHardRectilinearBlocks : {chips}\nNumTerminals : 0\n'
              'InterposerWidth : 30000\nInterposerHeight : 30000\n')
    power = ''.join(f'c{i} {rng.uniform(0, 50):.3f}\n' for i in range(chips))
    records = []
    for _ in range(nets):
        a, b = rng.sample(range(chips), 2)
        records.append('NetDegree : 2\n' + ''.join(
            f'c{c} B : %{rng.uniform(-50, 50):.4f} %{rng.uniform(-50, 50):.4f}\n' for c in (a, b)))
    netlist = f'NumNets : {nets}\nNumPins : {2*nets}\n' + ''.join(records)
    return import_case('synthetic', header + blocks, power, netlist)


def reference_length_um(case, placements):
    """Independent scalar reference: explicit CCW quarter-turn formulas per pin."""
    poses = {p['chiplet']: p for p in placements}
    total = 0.0
    for net in case['nets']:
        points = []
        for pin in net['pins']:
            p = poses[pin['chiplet']]
            x, y = float(pin['offset_x_um_decimal']), float(pin['offset_y_um_decimal'])
            x, y = {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[p['rotation_deg']]
            points.append((p['centre_x_um'] + x, p['centre_y_um'] + y))
        total += abs(points[0][0] - points[1][0]) + abs(points[0][1] - points[1][1])
    return total


class PlacementCoreTest(unittest.TestCase):
    def setUp(self):
        self.problem = Problem.from_imported(import_case('test', BLOCKS, POWER, NETS))

    def layout(self, a, b, rotation=(0, 0)):
        return Layout(np.array([a, b], dtype=float), np.array(rotation))

    def test_fixture_pin_lengths_match_hand_values(self):
        # a local offset=(1000,-200), b=(-500,500); b global=(7500,6500).
        for angle, expected_um in ((0, 7200), (90, 6800), (180, 8800), (270, 9200)):
            got = pin_manhattan_um(self.problem, self.layout((3000, 3000), (8000, 6000), (angle, 0))).sum()
            self.assertAlmostEqual(got, expected_um, places=9)

    def test_random_layouts_match_scalar_reference(self):
        rng = random.Random(2026111300)
        case = synthetic_case(rng)
        problem = Problem.from_imported(case)
        for _ in range(50):
            placements = [dict(chiplet=c['name'], centre_x_um=rng.randint(0, 30)*1000,
                               centre_y_um=rng.randint(0, 30)*1000, rotation_deg=rng.choice((0, 90, 180, 270)))
                          for c in case['chiplets']]
            got = pin_manhattan_um(problem, Layout.from_placements(problem, placements)).sum()
            self.assertAlmostEqual(got, reference_length_um(case, placements), delta=1e-6)

    def test_gap_bounds_and_rotated_extent(self):
        # a is 4000x2000, b is 1000x1000, carrier 10000x10000, gap 1000.
        self.assertTrue(is_legal(self.problem, self.layout((2000, 1000), (5500, 1000)), 1000))   # gap exactly 1000
        self.assertFalse(is_legal(self.problem, self.layout((2000, 1000), (5499, 1000)), 1000))
        self.assertEqual(violations(self.problem, self.layout((1999, 1000), (8000, 8000)), 1000)['outside'], ['a'])
        # Rotated a is 2000 wide: x in [0, 2000], so b at x=3500 keeps a 1000 gap.
        self.assertTrue(is_legal(self.problem, self.layout((1000, 2000), (3500, 2000), (90, 0)), 1000))
        self.assertFalse(is_legal(self.problem, self.layout((1000, 2000), (3500, 2000), (0, 0)), 1000))

    def test_thermal_conserves_energy_and_ignores_uniform_half_turn(self):
        problem = Problem.from_imported(synthetic_case(random.Random(7), chips=3, nets=10))
        centre = np.array([[6000., 6000.], [18000., 8000.], [10000., 22000.]])
        peaks = []
        for rotation in ((0, 0, 0), (180, 180, 0)):
            result = solve_peak(thermal_case_data(problem, Layout(centre, np.array(rotation)), 1000, 24))
            self.assertAlmostEqual(result['source_power_w'], problem.power_w.sum(), places=9)
            self.assertLess(abs(result['energy_balance_error_w']), 1e-6*result['source_power_w'] + 1e-9)
            self.assertGreaterEqual(result['min_rise_k'], -1e-9)
            peaks.append(result['peak_power_layer_c'])
        self.assertAlmostEqual(peaks[0], peaks[1], places=9)

    def test_illegal_layout_rejected_before_thermal_case(self):
        with self.assertRaises(ValueError):
            thermal_case_data(self.problem, self.layout((3000, 3000), (3000, 3000)), 1000)


if __name__ == '__main__':
    unittest.main()
