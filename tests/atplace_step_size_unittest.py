from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import atplace_temperature_feedback_unittest as fixture
from atplace_orientation_repair import candidate_pool
from atplace_temperature_feedback import run_search
from run_atplace_orientation import without_elapsed
from run_atplace_search import object_hash
from run_atplace_step_size import ChargedOracle, ledger, reachability, saved_inputs


class StepSizeTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.TemperatureFeedbackTest()
        self.fixture.setUp()

    def test_reused_responses_still_consume_query_budget_without_free_parents(self):
        f = self.fixture
        def response(data):
            return dict(f.solve(data), evaluated_case_sha256=object_hash(data))
        baseline = run_search(f.source, f.plan, 'temperature_guided', f.rows, f.cache, response)
        saved = saved_inputs(dict(thermal_records=baseline['thermal_records'][:5]))
        fresh_calls = []
        def fresh(data):
            fresh_calls.append(object_hash(data))
            return response(data)
        oracle = ChargedOracle(saved, fresh, lambda data, summary: None)
        actual = run_search(f.source, f.plan, 'temperature_guided', f.rows, f.cache, oracle)
        self.assertEqual(without_elapsed(actual), without_elapsed(baseline))
        self.assertEqual(actual['effort']['initial_parents'], 1)
        self.assertEqual(ledger(oracle.receipts)['charged_evaluations'], 10)
        self.assertEqual(ledger(oracle.receipts)['saved_response_returns'], 5)
        self.assertEqual(ledger(oracle.receipts)['actual_new_thermal_solves'], 5)
        self.assertEqual(len(fresh_calls), 5)
        self.assertEqual(len(f.cache), 1)

    def test_step_changes_coordinate_lattice_but_not_rectangle_orientation_class(self):
        f = self.fixture
        start = f.rows[0]
        original = {p['chiplet']: p for p in start['placement']}
        for step in (2000, 1000):
            moves, attempted = candidate_pool(f.source, [dict(label='start', placement=start['placement'])],
                                              f.plan['gap_um'], step, f.plan['seed'])
            self.assertEqual(attempted, 4*len(f.source['chiplets']))
            self.assertTrue(moves)
            for move in moves:
                changed = [(p['chiplet'], field, p[field]-original[p['chiplet']][field])
                           for p in move['placement'] for field in ('centre_x_um', 'centre_y_um')
                           if p[field] != original[p['chiplet']][field]]
                self.assertEqual(len(changed), 1)
                self.assertEqual(abs(changed[0][2]), step)
                self.assertEqual(changed[0][2] % 2000, 0 if step == 2000 else 1000)
                self.assertEqual([p['rotation_deg'] for p in move['placement']],
                                 [p['rotation_deg'] for p in start['placement']])
        target = deepcopy(start)
        rectangle = next(c for c in f.source['chiplets'] if c['width_um'] != c['height_um'])
        pose = next(p for p in target['placement'] if p['chiplet'] == rectangle['name'])
        pose['centre_x_um'] += 1000
        pose['rotation_deg'] = (pose['rotation_deg']+90) % 360
        report = reachability(f.source, start, target)
        self.assertEqual(len(report['coordinate_mod_2mm_mismatches']), 1)
        self.assertEqual(len(report['rectangle_orientation_class_mismatches']), 1)
        self.assertFalse(report['reference_reachability_proven'])


if __name__ == '__main__':
    unittest.main()
