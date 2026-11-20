import itertools
import unittest

import numpy as np

from chiplet_floorplanning.placement.slot_margin import choose_hot_slots


class SlotMarginTest(unittest.TestCase):
    def test_peak_bounds_survive_unobserved_cells_and_an_arbitrary_wire_restriction(self):
        r = np.random.default_rng(17).uniform(.01,.9,(11,8))
        for count in (0, 1, 4, 8):
            hot, bound = choose_hot_slots(r[:5],1.,3.,count)
            feasible = [s for s in itertools.combinations(range(8),count) if count == 0 or 0 in s]
            def peak(s, rows):
                return (rows.sum(axis=1)+2*rows[:,s].sum(axis=1)).max()
            optimum = min(peak(s,r) for s in feasible)
            self.assertLessEqual(bound["lower_k"], optimum + 1e-8)
            all_patterns = itertools.combinations(range(8),count)
            self.assertAlmostEqual(peak(hot,r[:5]), min(peak(s,r[:5]) for s in all_patterns))
            self.assertLessEqual(bound["conditional_k"],peak(hot,r[:5])+1e-8)
