import unittest

from chiplet_floorplanning.uncertainty import assess_timing_margin, compare_temperature_difference


class DecisionUncertaintyTest(unittest.TestCase):
    def test_missing_bound_is_not_zero_or_equivalence(self):
        self.assertEqual(assess_timing_margin(9., 10.)['status'], 'uncertainty_unquantified')
        self.assertEqual(compare_temperature_difference(.08)['status'], 'uncertainty_unquantified')

    def test_pairwise_ranking_and_overlap(self):
        self.assertEqual(compare_temperature_difference(.3, difference_bound_k=.12, evidence='constructed test')['status'], 'b_cooler_under_supplied_bound')
        self.assertEqual(compare_temperature_difference(-.3, difference_bound_k=.12, evidence='constructed test')['status'], 'a_cooler_under_supplied_bound')
        for delta in (-.12, 0, .12):
            self.assertEqual(compare_temperature_difference(delta, difference_bound_k=.12, evidence='constructed test')['status'], 'indistinguishable_within_uncertainty')

    def test_hold_can_control_robustness_and_zero_is_feasible(self):
        self.assertEqual(assess_timing_margin(9, .1, slack_bound_ns=.1, evidence='constructed test')['status'], 'feasible_under_supplied_bound')
        self.assertEqual(assess_timing_margin(9, -.11, slack_bound_ns=.1, evidence='constructed test')['status'], 'infeasible_under_supplied_bound')
        self.assertEqual(assess_timing_margin(9, -.1, slack_bound_ns=.1, evidence='constructed test')['status'], 'indistinguishable_within_uncertainty')

    def test_invalid_or_unsourced_bounds_fail(self):
        for bound in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                assess_timing_margin(1, 1, slack_bound_ns=bound, evidence='test')
        with self.assertRaises(ValueError):
            compare_temperature_difference(.1, difference_bound_k=.2)


if __name__ == '__main__':
    unittest.main()
