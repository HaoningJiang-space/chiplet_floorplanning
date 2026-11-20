import unittest

import numpy as np

from chiplet_floorplanning.placement.power_subspace import subspace_peaks


class PowerSubspaceTest(unittest.TestCase):
    def test_two_conserving_source_directions_reproduce_all_peaks(self):
        # Three coupled slots with ambient paths and one strongly cooled, unpowered cell.
        a = np.array([[4.,-1.,0.,0.], [-1.,4.,-1.,0.], [0.,-1.,3.,-.1], [0.,0.,-.1,50.]])
        b = np.eye(4)[:, :3]
        start = np.array([2., 2., 2.])
        pool = np.array([[2.,2.,2.], [2.4,1.7,1.9], [1.8,2.5,1.7], [2.2,2.2,1.6]])
        expected = np.linalg.solve(a, b@pool.T).max(axis=0)
        used = []
        def response(direction):
            used.append(direction)
            return np.linalg.solve(a, b@direction)
        base = np.linalg.solve(a, b@start)
        with self.assertRaisesRegex(ValueError, 'requires 2'):
            subspace_peaks(start, pool, base, response, 1)
        self.assertEqual(len(used), 0)
        peaks, d = subspace_peaks(start, pool, base, response, 2)
        self.assertEqual(len(used), 2)
        self.assertLess(d['kept_nodes'], d['active_nodes'])
        np.testing.assert_allclose(peaks, expected, atol=d['equivalent_peak_guard_k'], rtol=0)

    def test_identical_heat_maps_need_no_response(self):
        start = np.array([1.,2.])
        peaks, d = subspace_peaks(start, np.stack([start,start]), np.array([3.,4.]),
                                  lambda _: self.fail('unexpected response'), 0)
        np.testing.assert_array_equal(peaks, [4.,4.])
        self.assertEqual(d['rank'], 0)
