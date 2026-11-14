from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from bound_routing_screen import bounds, window_max
from chiplet_floorplanning.placement import Problem


def brute(points, size):
    # Some optimal closed square has its left edge on a point x and bottom edge on a point y.
    return max(int(((points[:, 0] >= x) & (points[:, 0] <= x + size)
                    & (points[:, 1] >= y) & (points[:, 1] <= y + size)).sum())
               for x in points[:, 0] for y in points[:, 1])


class RoutingBoundTest(unittest.TestCase):
    def test_window_max_matches_brute_force(self):
        rng = np.random.default_rng(4)
        for _ in range(30):
            points = np.round(rng.uniform(0, 5000, size=(rng.integers(1, 40), 2)) / 250) * 250
            self.assertEqual(window_max(points, 1000), brute(points, 1000))

    def test_closed_window_counts_boundary_and_duplicates(self):
        points = np.array([[0., 0.], [1000., 1000.], [1000., 1000.], [1001., 0.]])
        self.assertEqual(window_max(points, 1000), 3)

    def test_touching_dies_need_sides_longer_than_a_bin(self):
        tiny = Problem('tiny', ('a',), np.array([[1000., 3000.]]), np.ones(1), (10000., 10000.),
                       np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        with self.assertRaises(ValueError):
            bounds(tiny, 0)
        self.assertEqual(bounds(tiny, 1000)['escape_utilization_bound'], 0)


if __name__ == '__main__':
    unittest.main()
