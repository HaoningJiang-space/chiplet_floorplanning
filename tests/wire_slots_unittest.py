import itertools
import unittest

import numpy as np

from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.wire_slots import forced_edge_components, line_patterns


class WireSlotTest(unittest.TestCase):
    def test_compressed_orders_equal_exhaustive_pin_and_power_pairs(self):
        xy = np.array([[x, y] for y in (0., 21.) for x in (0., 9., 23.)])
        xy = xy[[4, 2, 1, 5, 0, 3]]
        sizes = np.full((6, 2), 2.)
        angles = np.array([90, 270, 0, 90, 180, 0])
        pins = np.array([[0, 1], [1, 2], [3, 5], [4, 2], [1, 5], [0, 0]])
        offsets = np.random.default_rng(17).uniform(-1., 1., (len(pins), 2, 2))
        p = Problem("mixed", tuple(map(str, range(6))), sizes, np.array([3., 1., 3., 2., 1., 2.]),
                    (50., 50.), pins, offsets)
        start = Layout(xy, angles)
        cap = pin_manhattan_um(p, start).sum()/1e6
        patterns, summary = line_patterns(p, start, cap)
        expected = {}
        line_identity_count = 0
        all_feasible = []
        xs, col = np.unique(xy[:, 0], return_inverse=True)
        ys, row = np.unique(xy[:, 1], return_inverse=True)
        for perm in itertools.permutations(range(6)):
            idx = np.array(perm)
            cost = pin_manhattan_um(p, Layout(xy[idx], angles)).sum()/1e6
            if cost > cap + 1e-9:
                continue
            all_feasible.append(perm)
            if (any(len(set(col[idx][col == k])) != 1 for k in range(len(xs)))
                    or any(len(set(row[idx][row == k])) != 1 for k in range(len(ys)))):
                continue
            line_identity_count += 1
            power = np.empty(6)
            power[idx] = p.power_w
            key = tuple(power)
            expected[key] = min(cost, expected.get(key, np.inf))
        self.assertEqual({tuple(c.power_w) for c in patterns}, set(expected))
        for c in patterns:
            measured = pin_manhattan_um(p, Layout(xy[c.chip_to_slot], angles)).sum()/1e6
            self.assertAlmostEqual(c.wire_m, expected[tuple(c.power_w)])
            self.assertAlmostEqual(c.wire_m, measured)
        self.assertEqual(summary['feasible_identity_assignments'], line_identity_count)
        if len(all_feasible) > 1:
            self.assertFalse(forced_edge_components(p, start, cap)['all_relative_positions_fixed'])
