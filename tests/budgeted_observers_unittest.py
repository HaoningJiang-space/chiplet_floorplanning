import unittest

import numpy as np

from chiplet_floorplanning.placement.observer_search import search_observers


class BudgetedObserversTest(unittest.TestCase):
    def test_last_witness_bounds_unchecked_layouts_without_spending_another_check(self):
        gains = [0., 1., 2., 1.5]
        witnesses = np.array([[0., 1., 4., 3.], [0., 2., 2., 1.6]])

        def verify(i):
            return gains[i], i - 1

        for budget, checked, gap in ((0, [], 6.), (1, [1], 3.), (2, [1, 2], 0.)):
            result = search_observers([0., 6., 5., 4.], [1.]*4, verify,
                                      lambda w: witnesses[w], max_checks=budget)
            self.assertEqual(result.checked, checked)
            self.assertAlmostEqual(result.remaining_gain_bound_k, gap, places=6)
            self.assertGreaterEqual(result.best_gain_k + result.remaining_gain_bound_k, max(gains))
