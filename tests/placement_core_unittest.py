from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from atplace_pin_geometry import make_thermal_case, pin_objective, placement_geometry
from import_atplace_cases import parse_case as import_case
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.placement import (Layout, Problem, is_legal, pin_manhattan_um,
                                             centre_manhattan_um, solve_peak, thermal_case_data)
from chiplet_floorplanning.power import rasterize


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


def random_placements(rng, case):
    return [dict(chiplet=c['name'], centre_x_um=rng.randint(0, 30)*1000, centre_y_um=rng.randint(0, 30)*1000,
                 rotation_deg=rng.choice((0, 90, 180, 270))) for c in case['chiplets']]


def legacy_legal(case, placements, gap_um):
    try:
        placement_geometry(case, placements, gap_um)
        return True
    except ValueError:
        return False


class PlacementCoreTest(unittest.TestCase):
    def test_fixture_pin_lengths_match_hand_values(self):
        case = import_case('test', BLOCKS, POWER, NETS)
        problem = Problem.from_imported(case)
        for angle, expected_um in ((0, 7200), (90, 6800), (180, 8800), (270, 9200)):
            layout = Layout(np.array([[3000., 3000.], [8000., 6000.]]), np.array([angle, 0]))
            self.assertAlmostEqual(pin_manhattan_um(problem, layout).sum(), expected_um, places=9)

    def test_random_layouts_match_legacy_legality_and_lengths(self):
        rng = random.Random(2026111300)
        case = synthetic_case(rng)
        problem = Problem.from_imported(case)
        legal = 0
        for _ in range(400):
            placements = random_placements(rng, case)
            layout = Layout.from_placements(problem, placements)
            expected = legacy_legal(case, placements, 1000)
            self.assertEqual(is_legal(problem, layout, 1000), expected)
            if expected:
                legal += 1
                old = pin_objective(case, placements, 1000)
                self.assertAlmostEqual(pin_manhattan_um(problem, layout).sum()/1e6, old['total_pin_manhattan_m'], places=9)
                self.assertAlmostEqual(centre_manhattan_um(problem, layout).sum()/1000, old['total_centre_manhattan_mm'], places=9)
        self.assertGreater(legal, 10)

    def test_thermal_system_is_identical_to_legacy_recipe(self):
        rng = random.Random(7)
        case = synthetic_case(rng, chips=4, nets=20)
        problem = Problem.from_imported(case)
        placements = next(p for p in iter(lambda: random_placements(rng, case), None) if legacy_legal(case, p, 1000))
        systems = []
        for data in (make_thermal_case(case, placements, 1000, 24),
                     thermal_case_data(problem, Layout.from_placements(problem, placements), 1000, 24)):
            parsed = parse_case(data)
            a, b, *_ = assemble_package(parsed, rasterize(parsed)[0])
            systems.append((a, b))
        self.assertEqual(abs(systems[0][0] - systems[1][0]).max(), 0)
        np.testing.assert_array_equal(systems[0][1], systems[1][1])
        result = solve_peak(thermal_case_data(problem, Layout.from_placements(problem, placements), 1000, 24))
        self.assertAlmostEqual(result['energy_balance_error_w'], 0, delta=1e-6*result['source_power_w'] + 1e-9)
        self.assertGreaterEqual(result['min_rise_k'], -1e-9)

    def test_illegal_layout_rejected_before_thermal_case(self):
        case = import_case('test', BLOCKS, POWER, NETS)
        problem = Problem.from_imported(case)
        overlap = Layout(np.array([[3000., 3000.], [3000., 3000.]]), np.array([0, 0]))
        with self.assertRaises(ValueError):
            thermal_case_data(problem, overlap, 1000)


if __name__ == '__main__':
    unittest.main()
