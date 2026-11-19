import unittest

import numpy as np

from chiplet_floorplanning.placement.dominance import peak_curve, potential_hotspots, simplex_worst_excess, worst_excess


class DominanceTests(unittest.TestCase):
    def test_one_sided_certificate(self):
        # A has no switches; B changes its hottest cell at w=1/4.
        candidate = peak_curve([2.8, np.nan], [2.8, np.nan])
        baseline = peak_curve([3, 2], [0, 3])
        np.testing.assert_allclose(worst_excess(candidate, baseline), [.55, .25])
        self.assertAlmostEqual(worst_excess(baseline, candidate)[0], .2)

    def test_upper_envelope_against_independent_all_intersections(self):
        first = np.array([5, 5, 4, 3, 2, 0, -1], float)
        second = np.array([-1, -1, -2, 4, 4.5, 6, 4], float)
        slope = second - first
        crossings = [(first[i] - first[j]) / (slope[j] - slope[i])
                     for i in range(len(first)) for j in range(i) if slope[j] != slope[i]]
        weights = np.array([0, 1, *(w for w in crossings if 0 < w < 1)])
        curve = peak_curve(first, second)
        np.testing.assert_allclose(curve.at(weights), (first + weights[:, None] * slope).max(1))
        self.assertGreater(len(curve.weights), 3)

    def test_support_and_constant_field(self):
        with self.assertRaises(ValueError):
            peak_curve([1, np.nan], [np.nan, 1])
        curve = peak_curve([2, 1], [2, 1])
        np.testing.assert_array_equal(curve.weights, [0, 1])
        np.testing.assert_array_equal(curve.temperatures, [2, 2])

    def test_simplex_interior_worse_than_every_edge(self):
        a = np.ones((3, 3)) + np.eye(3)
        b = np.full((3, 3), .1) + np.eye(3) * 2.9
        reduced = potential_hotspots(np.vstack((a, a[0], a[0] - .2)))
        self.assertEqual(len(reduced), 3)
        excess, weights = simplex_worst_excess(reduced, b)
        self.assertAlmostEqual(excess, 4/15)
        np.testing.assert_allclose(weights, np.full(3, 1/3))
        self.assertAlmostEqual(worst_excess(peak_curve(*a[:, :2].T), peak_curve(*b[:, :2].T))[0], -.05)
