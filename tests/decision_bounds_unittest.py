import copy
import unittest

from chiplet_floorplanning.decision import summarize_decisions


def row(name, temperature, route=True):
    return dict(id=name, layout_id=name, geometry_feasible=True,
                thermal=dict(peak_c=temperature), routing_status='feasible' if route else 'search_failed',
                timing={mode: dict(status='analyzed', timing_feasible=True, worst_setup_ns=1., worst_hold_ns=2.)
                        for mode in ('reference', 'feedback')} if route else {})


class DecisionBoundTests(unittest.TestCase):
    def test_unknown_better_route_keeps_bound_open(self):
        result = summarize_decisions([row('cold_unknown', 30, False), row('warm_witness', 35)])
        self.assertFalse(result['stages']['timing_feedback']['certified_numerical_optimum'])
        self.assertEqual(result['timing_temperature_cost']['feedback']['penalty_bounds_k'], [0, 5])
        self.assertIsNone(result['timing_temperature_cost']['feedback']['exact_penalty_k'])

    def test_thermal_lower_bound_witness_certifies_without_all_routes(self):
        result = summarize_decisions([row('cold_witness', 30), row('warm_unknown', 35, False)])
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


if __name__=='__main__':
    unittest.main()
