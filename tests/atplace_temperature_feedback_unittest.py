from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case
from atplace_incremental_pins import IncidentPinRepair
from atplace_routing_screen import DEFAULT_RESOURCES
from atplace_temperature_feedback import run_search
from run_atplace_orientation import without_elapsed
from run_atplace_search import object_hash


class TemperatureFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.source = parse_case('test', BLOCKS, POWER, NETS)
        self.source['interposer_width_um'] = self.source['interposer_height_um'] = 20000
        self.plan = dict(seed=7, gap_um=1000, step_um=2000, resources=deepcopy(DEFAULT_RESOURCES),
                         length_cap_m=1, temperature_cap_c=100, resolution=8,
                         thermal_budget_per_arm=10, parent_cap=128, proposal_cap=1024,
                         geometry_check_cap=10000, net_length_evaluation_cap=100000,
                         improvement_tolerance_k=1e-6)
        poses = [dict(chiplet='a', centre_x_um=6000, centre_y_um=6000, rotation_deg=0),
                 dict(chiplet='b', centre_x_um=15000, centre_y_um=15000, rotation_deg=0)]
        p = IncidentPinRepair(self.source, 1000).prepare(poses, DEFAULT_RESOURCES)
        self.rows = [dict(row_index=0, placement=p['placement'], layout_key=p['layout_key'],
                          thermal_key=p['thermal_key'], pin_length_m=p['pin_length_m'],
                          pin_length_um_decimal=p['pin_length_um_decimal'], peak_c=94,
                          thermal_response_id='warm', thermal_queries_so_far=0, thermal_cache_hit=True)]
        self.cache = {object_hash(p['thermal_key']): dict(response_id='warm', thermal=dict(peak_power_layer_c=94))}

    def solve(self, data):
        # Deliberately synthetic monotonic objective to test the search mechanism,
        # not a claimed thermal model: the 20 mm carrier has a 90 mm offset.
        a = next(c for c in data['chiplets'] if c['id'] == 'a')
        centre_x_mm = a['placement_mm']['x']-90+2
        return dict(peak_power_layer_c=100-centre_x_mm)

    def test_both_methods_have_multistep_expansion_and_same_budget(self):
        for method in ('temperature_blind', 'temperature_guided'):
            result = run_search(self.source, self.plan, method, self.rows, self.cache, self.solve)
            self.assertGreater(result['effort']['added_parents'], 0)
            self.assertEqual(result['effort']['new_thermal_queries'], 10)
            self.assertTrue(any(e['parent_generation'] > 0 for e in result['events']))
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(self.cache), 1)

    def test_blind_parent_choices_do_not_depend_on_observed_temperature(self):
        a = run_search(self.source, self.plan, 'temperature_blind', self.rows, self.cache, self.solve)
        b = run_search(self.source, self.plan, 'temperature_blind', self.rows, self.cache,
                       lambda data: dict(peak_power_layer_c=94))
        self.assertEqual([(e['parent_row'], e['placement']) for e in a['events']],
                         [(e['parent_row'], e['placement']) for e in b['events']])

    def test_saved_response_replay_preserves_parent_choices_and_costs(self):
        expected = run_search(self.source, self.plan, 'temperature_guided', self.rows, self.cache, self.solve)
        saved = iter(expected['thermal_records'])
        def solve(data):
            item = next(saved)
            self.assertEqual(object_hash(data), item['evaluated_case_sha256'])
            return item['thermal']
        actual = run_search(self.source, self.plan, 'temperature_guided', self.rows, self.cache, solve)
        self.assertEqual(without_elapsed(expected), without_elapsed(actual))
        self.assertIsNone(next(saved, None))


if __name__ == '__main__':
    unittest.main()
