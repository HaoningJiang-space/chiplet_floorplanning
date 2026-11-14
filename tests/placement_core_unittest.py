from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case as import_case
from chiplet_floorplanning.placement.methods import METHODS, Run, ranks_and_crowding
from chiplet_floorplanning.placement.evaluate import shelf_pack
from chiplet_floorplanning.placement.search import layout_key, length_target, mutate
from chiplet_floorplanning.placement import (Evaluator, boxes, Layout, Problem, Superposition, coolest_within,
                                             is_legal, pareto_front, pin_manhattan_um, sample_legal,
                                             shortest_within, solve_peak, thermal_case_data, violations)

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

    def test_metrics_select_single_real_layouts(self):
        length, peak = np.array([3., 1., 2., 1.]), np.array([90., 95., 92., 94.])
        self.assertEqual(pareto_front(length, peak), [3, 2, 0])
        self.assertEqual(coolest_within(length, peak, 2.0), 2)
        self.assertIsNone(coolest_within(length, peak, 0.5))
        self.assertEqual(shortest_within(length, peak, 92.0), 2)

    def test_sampler_is_legal_and_evaluator_shares_thermal_problems(self):
        problem = Problem.from_imported(synthetic_case(random.Random(3), chips=3, nets=10))
        rng = np.random.default_rng(0)
        layouts = [sample_legal(problem, 1000, rng) for _ in range(5)]
        self.assertTrue(all(is_legal(problem, layout, 1000) for layout in layouts))
        evaluator = Evaluator(problem, 1000, resolution=24)
        turned = Layout(layouts[0].centre_um, (layouts[0].rotation_deg + 180) % 360)
        peaks = evaluator.peaks_c([layouts[0], turned])
        self.assertEqual(evaluator.solves, 1)
        self.assertEqual(peaks[0], peaks[1])

    def test_superposition_is_exact_for_one_isolated_chip_up_to_sampling(self):
        problem = Problem.from_imported(synthetic_case(random.Random(5), chips=2, nets=4))
        problem = Problem(problem.name, problem.names[:1], problem.size_um[:1], problem.power_w[:1],
                          problem.carrier_um, np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        layout = Layout(np.array([[15000., 15000.]]), np.array([0]))
        model = Superposition(problem, 1000, resolution=32)
        exact = solve_peak(thermal_case_data(problem, layout, 1000, 32))['peak_power_layer_c']
        # Same physics except the enlarged kernel carrier and point sampling of cell values.
        self.assertLess(abs(model.peak_c(layout) - exact), 0.05*(exact - 45))

    def test_length_target_is_single_chip_optimum(self):
        problem = Problem.from_imported(synthetic_case(random.Random(11), chips=4, nets=120))
        layout = sample_legal(problem, 1000, np.random.default_rng(1))
        for k in range(problem.count):
            centre = layout.centre_um.copy()
            centre[k] = length_target(problem, layout, k)
            best = pin_manhattan_um(problem, Layout(centre, layout.rotation_deg)).sum()
            for shift in ((137, 0), (-137, 0), (0, 59), (0, -59)):
                moved = centre.copy()
                moved[k] += shift
                self.assertGreaterEqual(pin_manhattan_um(problem, Layout(moved, layout.rotation_deg)).sum(), best - 1e-6)

    def test_every_method_respects_fv_budget_including_duplicated_start_set(self):
        problem = Problem.from_imported(synthetic_case(random.Random(13), chips=3, nets=40))
        start = [sample_legal(problem, 1000, np.random.default_rng(2)) for _ in range(3)]
        for name, method in METHODS.items():
            for budget in (1, 12):
                with self.subTest(method=name, budget=budget):
                    with Evaluator(problem, 1000, resolution=16) as evaluator:
                        run = Run(evaluator, budget)
                        method(run, start + start, np.random.default_rng(3), batch=4, length_caps_m=(1e9,))
                    length, peak, cost = run.arrays()
                    self.assertLessEqual(evaluator.solves, budget)
                    self.assertEqual(len({layout_key(l) for l in run.layouts}), len(run.layouts))
                    self.assertTrue(all(is_legal(problem, l, 1000) for l in run.layouts))
                    self.assertTrue(np.all(np.diff(cost) >= 0) and cost[-1] == evaluator.solves)

    def test_epsilon_search_spends_solves_only_below_the_length_cap(self):
        problem = Problem.from_imported(synthetic_case(random.Random(17), chips=3, nets=60))
        rng = np.random.default_rng(5)
        start = [sample_legal(problem, 1000, rng) for _ in range(4)]
        with Evaluator(problem, 1000, resolution=16) as evaluator:
            run = Run(evaluator, 16)
            run.evaluate(start)
            cap = float(np.median(run.arrays()[0]))
            METHODS['epsilon'](run, start, rng, batch=4, length_caps_m=(cap,))
        length = run.arrays()[0]
        self.assertTrue(np.all(length[len(start):] <= cap + 1e-12))

    def test_ranks_and_crowding(self):
        length, peak = np.array([1., 2., 3., 2., 3.]), np.array([3., 2., 1., 3., 3.])
        rank, crowd = ranks_and_crowding(length, peak)
        self.assertEqual(list(rank), [0, 0, 0, 1, 2])
        self.assertTrue(np.isinf(crowd[[0, 2]]).all() and np.isfinite(crowd[1]))

    def test_length_target_ignores_nets_inside_the_moving_chip(self):
        # Chip a carries one internal net and one net to b; only the latter sets the target.
        problem = Problem('internal', ('a', 'b'), np.array([[4000., 4000.], [2000., 2000.]]), np.ones(2),
                          (30000., 30000.), np.array([[0, 0], [0, 1]]),
                          np.array([[[-1500., 0.], [1500., 0.]], [[0., 0.], [0., 0.]]]))
        layout = Layout(np.array([[5000., 5000.], [20000., 5000.]]), np.array([0, 0]))
        self.assertTrue(np.allclose(length_target(problem, layout, 0), [20000., 5000.]))

    def test_non_integer_rotation_is_rejected_not_truncated(self):
        placements = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=90.9),
                      dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        with self.assertRaises(ValueError):
            Layout.from_placements(self.problem, placements)

    def test_shelf_fallback_finds_zero_slack_case5_packing(self):
        # Case5 geometry: six 8x9 mm and six 9x9 mm dies in 37x37 mm with 1 mm gaps
        # fit only as rows of height 9+9+8+8 mm plus three gaps.
        problem = Problem('case5_like', tuple(f'c{i}' for i in range(12)),
                          np.array([[8000., 9000.]]*6 + [[9000., 9000.]]*6), np.ones(12), (37000., 37000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        layout = sample_legal(problem, 1000, np.random.default_rng(0), uniform_tries=1, packed_tries=1)
        self.assertTrue(is_legal(problem, layout, 1000))
    def test_shelf_fallback_stays_on_grid_so_search_can_move(self):
        # Half-millimetre die sizes used to give off-grid shelf corners; every move was then illegal.
        sizes = np.array([[2500., 2500.]]*8 + [[3500., 1500.]]*4)
        problem = Problem('half_mm', tuple(f'c{i}' for i in range(12)), sizes, np.ones(12), (16000., 16000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        rng = np.random.default_rng(0)
        layout = shelf_pack(problem, 1000, rng)
        corners = boxes(problem, layout)[:, :2]
        self.assertTrue(np.allclose(corners % 1000, 0))
        moves = [mutate(problem, layout, rng, 1000) for _ in range(300)]
        self.assertTrue(any(m is not None for m in moves))

    def test_failed_solutions_and_nan_metrics_are_rejected(self):
        from scipy import sparse
        from chiplet_floorplanning.package import checked_solution
        matrix = sparse.identity(2, format='csr')
        with self.assertRaises(ValueError):
            checked_solution(matrix, np.ones(2), np.ones(2), np.array([1., np.nan]))
        with self.assertRaises(ValueError):
            coolest_within([1., 1.], [100., np.nan], 2.)
        with self.assertRaises(ValueError):
            pareto_front([1., 2.], [np.nan, 1.])

    def test_superposition_refuses_carriers_its_kernel_cannot_cover(self):
        problem = Problem('wide', ('a',), np.array([[4000., 4000.]]), np.ones(1), (59000., 61000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        with self.assertRaises(ValueError):
            Superposition(problem, 1000, resolution=16)


if __name__ == '__main__':
    unittest.main()
