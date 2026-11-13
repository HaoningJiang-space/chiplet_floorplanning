from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_constrained_selection import selection_key, run_policy
from atplace_pin_geometry import placement_geometry
from import_atplace_cases import parse_case as import_case
from atplace_import_unittest import BLOCKS, POWER, NETS


class ConstrainedSelectionTest(unittest.TestCase):
    def key(self, temperature, length, cap=10.):
        return selection_key(dict(peak_c=temperature, pin_length_m=length), cap)

    def test_feasibility_precedes_arbitrarily_lower_temperature(self):
        self.assertLess(self.key(110., 10.), self.key(60., 10.000001))
        self.assertLess(self.key(110., 10.1), self.key(60., 12.))

    def test_feasible_temperature_precedes_shorter_distance(self):
        self.assertLess(self.key(100., 10.), self.key(101., 1.))
        self.assertLess(self.key(100., 9.), self.key(100., 10.))
        self.assertLess(self.key(100., 11.), self.key(101., 11.))

    def test_exact_boundary_and_common_temperature_offset(self):
        self.assertEqual(self.key(80., 10.)[0], 0)
        self.assertEqual(self.key(80., 10.+1e-12)[0], 1)
        rows = [(100., 10.), (60., 11.), (101., 1.), (90., 11.), (110., 10.1)]
        order = sorted(range(len(rows)), key=lambda i:self.key(*rows[i]))
        shifted = sorted(range(len(rows)), key=lambda i:self.key(rows[i][0]+273.15, rows[i][1]))
        self.assertEqual(order, shifted)

    def test_search_keeps_archive_and_budget_while_selecting_feasible_population(self):
        source = import_case('test', BLOCKS, POWER, NETS)
        a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
             dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        b = deepcopy(a)
        b[0]['centre_y_um'] += 1000
        plan = dict(seed=2026111200, gap_um=1000, grid_um=1000, population=2,
            proposal_cap=200, candidate_check_cap=100000, pin_call_cap=1000, thermal_budget=8,
            length_cap_m=.0072, temperature_cap_c=80., initialization=dict(placements=[a, b],
            construction_attempts=1, candidate_checks=0, elapsed_seconds=0.))
        result = run_policy(source, plan, lambda d:dict(numerical_admission_passed=True, peak_power_layer_c=80.))
        self.assertEqual(result['status'], 'complete_thermal_budget')
        self.assertEqual(result['effort']['thermal_queries'], 8)
        self.assertEqual(result['effort']['illegal_proposals'], 0)
        self.assertEqual([r['placement'] for r in result['rows'][:2]], [a, b])
        last_feasible = sum(r['pin_length_m'] <= plan['length_cap_m'] for r in result['rows'][:2])
        for generation in result['generation_records']:
            keys = [list(selection_key(result['rows'][i], plan['length_cap_m'])) for i in generation['population_rows']]
            self.assertEqual(generation['selection_keys'], keys)
            self.assertEqual(keys, sorted(keys))
            self.assertGreaterEqual(generation['distance_feasible_count'], last_feasible)
            last_feasible = generation['distance_feasible_count']
        eligible = [r for r in result['rows'] if r['pin_length_m'] <= plan['length_cap_m']]
        self.assertEqual(result['physical_comparison']['temperature_at_length']['selected']['peak_c'],
                         min(r['peak_c'] for r in eligible))
        reverse = [r for r in result['rows'] if r['peak_c'] <= plan['temperature_cap_c']]
        self.assertEqual(result['physical_comparison']['length_at_temperature']['selected']['pin_length_m'],
                         min(r['pin_length_m'] for r in reverse))
        for r in result['rows']:
            placement_geometry(source, r['placement'], 1000)


if __name__ == '__main__':
    unittest.main()
