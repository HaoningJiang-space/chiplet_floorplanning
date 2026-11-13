from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import atplace_temperature_feedback_unittest as feedback_fixture
from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import candidate_pool
from atplace_temperature_feedback import run_search
from run_atplace_search import object_hash


class TightBudgetTest(unittest.TestCase):
    def test_over_budget_cold_cached_candidate_cannot_enter_either_search(self):
        fixture = feedback_fixture.TemperatureFeedbackTest()
        fixture.setUp()
        plan = deepcopy(fixture.plan)
        warm = fixture.rows[0]
        plan.update(length_cap_m=warm['pin_length_m'], proposal_cap=1)
        seed = int(object_hash([plan['seed'], warm['layout_key']]), 16)
        moves, _ = candidate_pool(fixture.source, [dict(label='0', placement=warm['placement'])],
                                  plan['gap_um'], plan['step_um'], seed)
        candidate = IncidentPinRepair(fixture.source, plan['gap_um']).prepare(moves[0]['placement'], plan['resources'])
        self.assertGreater(candidate['pin_length_m'], plan['length_cap_m'])
        cache = deepcopy(fixture.cache)
        cache[object_hash(candidate['thermal_key'])] = dict(
            response_id='deliberately_cold_over_budget', thermal=dict(peak_power_layer_c=1))
        def forbidden_solve(data):
            self.fail('An over-budget candidate must not consume a thermal query')
        for method in ('temperature_blind', 'temperature_guided'):
            with self.subTest(method=method):
                result = run_search(fixture.source, plan, method, fixture.rows, cache, forbidden_solve)
                self.assertEqual(result['effort']['length_rejections'], 1)
                self.assertEqual(result['effort']['new_thermal_queries'], 0)
                self.assertEqual(result['effort']['thermal_cache_hits'], 0)
                self.assertEqual(result['effort']['added_parents'], 0)
                self.assertEqual(result['rows'], fixture.rows)
                self.assertEqual(result['physical_comparison']['temperature_at_length']['selected']['peak_c'], 94)


if __name__ == '__main__':
    unittest.main()
