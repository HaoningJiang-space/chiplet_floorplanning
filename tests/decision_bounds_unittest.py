import copy
import unittest

from chiplet_floorplanning.decision import summarize_decisions


def row(name, temperature, route=True):
    return dict(id=name, layout_id=name, profile='test', geometry_feasible=True,
                thermal=dict(peak_c=temperature), routing_status='feasible' if route else 'search_failed',
                timing={mode: dict(status='analyzed', timing_feasible=True, worst_setup_ns=1., worst_hold_ns=2.)
                        for mode in ('reference', 'feedback')} if route else {})


class DecisionBoundTests(unittest.TestCase):
    def test_unknown_better_route_keeps_bound_open(self):
        result = summarize_decisions([row('cold_unknown', 30, False), row('warm_witness', 35)],
                                     expected_layout_ids=['cold_unknown', 'warm_witness'], expected_profile='test')
        self.assertFalse(result['stages']['timing_feedback']['certified_numerical_optimum'])
        self.assertEqual(result['timing_temperature_cost']['feedback']['penalty_bounds_k'], [0, 5])
        self.assertIsNone(result['timing_temperature_cost']['feedback']['exact_penalty_k'])

    def test_thermal_lower_bound_witness_certifies_without_all_routes(self):
        result = summarize_decisions([row('cold_witness', 30), row('warm_unknown', 35, False)],
                                     expected_layout_ids=['cold_witness', 'warm_unknown'], expected_profile='test')
        self.assertTrue(result['stages']['timing_feedback']['certified_numerical_optimum'])
        self.assertEqual(result['timing_temperature_cost']['feedback']['exact_penalty_k'], 0)
        self.assertFalse(result['model_uncertainty_bound_available'])

    def test_missing_heat_or_route_dependent_power_rejects_proof(self):
        a = row('a', 30); b = row('b', 31); b['layout_id'] = 'a'
        with self.assertRaises(ValueError):
            summarize_decisions([a, b])
        b = copy.deepcopy(a); del b['thermal']
        with self.assertRaises(ValueError):
            summarize_decisions([b])

    def test_no_declared_domain_cannot_prove_optimum_or_empty_set(self):
        for rows in ([], [row('only_supplied', 35)]):
            result = summarize_decisions(rows)
            self.assertFalse(result['domain_coverage_verified'])
            self.assertIsNone(result['stages']['routing']['lower_bound_c'])
            self.assertFalse(result['stages']['routing']['certified_numerical_optimum'])
            self.assertFalse(result['stages']['routing']['empty_set_proven'])

    def test_missing_extra_and_mixed_profile_fail_closed(self):
        for rows in ([row('a', 30)], [row('a', 30), row('b', 31), row('extra', 29)],
                     [row('a', 30), dict(row('b', 31), profile='different')]):
            with self.assertRaises(ValueError):
                summarize_decisions(rows, expected_layout_ids=['a', 'b'], expected_profile='test')


if __name__=='__main__':
    unittest.main()
