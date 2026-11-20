import itertools
import unittest
from collections import Counter
from pathlib import Path
import sys

import numpy as np

from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.linked_slots import linked_patterns
from chiplet_floorplanning.placement.problem import Layout, Problem

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_power_crossings import hot_to_cold
from continuous_row_exchanges import row_exchanges


class LinkedSlotTest(unittest.TestCase):
    def test_two_die_exchange_has_exact_minimum_separation(self):
        p = Problem('pair', ('a', 'b'), np.full((2, 2), 1000.), np.array([1., 3.]),
                    (10000., 8000.), np.array([[0, 1]]), np.zeros((1, 2, 2)))
        start = Layout(np.array([[5000., 2000.], [5000., 4000.]]), np.zeros(2, int))
        self.assertEqual(hot_to_cold(p, start, 2.)['unresolved_pairs'], 1)
        candidates, _ = row_exchanges(p, start, (.002, 2.))
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(pin_manhattan_um(p, candidates[0][1])[0], 1100.)
        candidates, records = row_exchanges(p, start, (.001, 1.))
        self.assertEqual(len(candidates), 0)
        self.assertAlmostEqual(records[0]['min_longest_mm_without_total_cap'], 1.1)
        self.assertAlmostEqual(records[0]['min_total_m_without_link_cap'], .0011)

    def test_joint_domains_against_all_assignments(self):
        xy = np.array([[x, y] for y in (5., 22.) for x in (3., 15., 28.)])
        turn = np.array([0, 270, 90, 180, 90, 0])
        pins = np.array([[0, 1], [0, 1], [1, 3], [3, 2], [2, 4], [5, 1], [3, 3]])
        offsets = np.random.default_rng(9).uniform(-1., 1., (len(pins), 2, 2))
        p = Problem('tiny', tuple(map(str, range(6))), np.full((6, 2), 2.),
                    np.array([1., 3., 2., 2., 1., 3.]), (32., 30.), pins, offsets)
        start = Layout(xy, turn)
        all_points = []
        initial = pin_manhattan_um(p, start)
        for perm in itertools.permutations(range(6)):
            idx = np.array(perm)
            wire = pin_manhattan_um(p, Layout(xy[idx], turn))
            power = np.empty_like(p.power_w)
            power[idx] = p.power_w
            all_points.append((sum(idx != np.arange(6)), tuple(power), wire.sum()/1e6, wire.max()/1000))
        for k, total, longest in ((0, 1., 1.), (4, 1., 1.),
                (6, initial.sum()/1e6, initial.max()/1000), (6, 0., 1.)):
            with self.subTest(k=k, total=total):
                expected = {}
                counts = Counter()
                for moved, power, wire, maximum in all_points:
                    if moved <= k and wire <= total + 1e-9 and maximum <= longest + 1e-9:
                        counts[moved] += 1
                        expected[power] = min(wire, expected.get(power, np.inf))
                patterns, stats = linked_patterns(p, start, total, longest, max_moved=k)
                self.assertTrue(stats['complete'])
                self.assertEqual(stats['by_moved'], dict(counts))
                self.assertEqual({tuple(v.power_w) for v in patterns}, set(expected))
                for v in patterns:
                    self.assertAlmostEqual(v.wire_m, expected[tuple(v.power_w)])
                    np.testing.assert_array_equal(v.power_w[v.chip_to_slot], p.power_w)
        _, bounded = linked_patterns(p, start, 1., 1., node_limit=1)
        self.assertFalse(bounded['complete'])
