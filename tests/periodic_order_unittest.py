import unittest
from itertools import product

import numpy as np
from scipy.sparse import csc_matrix

from chiplet_floorplanning.placement.periodic import balanced_orders, cycle_trace, periodic_pulse, quota_peak


class PeriodicOrderTests(unittest.TestCase):
    def test_end_of_step_phase_against_closed_form(self):
        dt, cap = .08, .3
        factor = 1/(1+dt/cap)
        steady, pulse = periodic_pulse(csc_matrix(np.eye(2)), np.full(2, cap), np.eye(2), 2*dt, 2, 8)
        for order, steps_on in [("01010101", 2), ("00001111", 8)]:
            trace = cycle_trace(steady[:, 0], pulse, order)
            self.assertAlmostEqual(trace.max(), 1/(1+factor**steps_on))
            # Full stationary power trace must satisfy the chronological recurrence,
            # including the link from the last sample back to the first.
            source = np.eye(2)[np.repeat(list(map(int, order)), 2)]
            np.testing.assert_allclose(trace, factor*np.roll(trace, 1, axis=0) + (1-factor)*source)

    def test_quota_with_delayed_signed_responses(self):
        base = np.array([.5, .1])
        pulse = np.array([[1, -2], [-1, 3], [4, -1], [-2, 4], [3, 1], [-1, 2]], dtype=float)
        for count in range(4):
            examples = ["".join(o) for o in product("01", repeat=3) if o.count("1") == count]
            expected = max(cycle_trace(base, pulse, order).max() for order in examples)
            self.assertAlmostEqual(quota_peak(base, pulse, 3, count), expected)
        self.assertEqual(len(balanced_orders(8)), 10)
