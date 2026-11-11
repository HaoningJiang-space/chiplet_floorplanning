import copy
from pathlib import Path
import unittest

import numpy as np

from chiplet_floorplanning.characterization import interpolate_cell, sample_instance_temperature, normalize_gf_json, build_temperature_models
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.timing import parse_sta_log


class CharacterizationTests(unittest.TestCase):
    def test_missing_units_and_incomplete_assignment_rejected(self):
        for locations in ({}, {'coordinate_unit': 'um', 'instances': {}}, {'coordinate_unit': 'mm', 'instances': {}}):
            with self.assertRaises(ValueError):
                build_temperature_models(None, None, locations, '/unused', '/unused')

    def test_interpolation_identity_and_no_extrapolation(self):
        a = {'values': [[1, 2]], 'max_transition': 2.0}
        b = {'values': [[3, 6]], 'max_transition': 3.0}
        self.assertEqual(interpolate_cell(a, b, 0), a)
        self.assertEqual(interpolate_cell(a, b, 1), b)
        self.assertEqual(interpolate_cell(a, b, 0.5), {'values': [[2, 4]], 'max_transition': 2.0})
        for fraction in (-1, 2, float('nan')):
            with self.assertRaises(ValueError):
                interpolate_cell(a, b, fraction)

    def test_regrid_analytic_bilinear_common_domain(self):
        a = {'index_1': [0, 1, 3], 'index_2': [0, 2], 'values': [[0, 2], [2, 4], [6, 8]]}
        b = {'index_1': [1, 2, 4], 'index_2': [0, 1, 2], 'values': [[5, 6, 7], [7, 8, 9], [11, 12, 13]]}
        c = interpolate_cell(a, b, 0.5)
        self.assertEqual(c['index_1'], [1, 2, 3])
        for i, x in enumerate(c['index_1']):
            for j, y in enumerate(c['index_2']):
                self.assertAlmostEqual(c['values'][i][j], 2*x+y+1.5)
        bad = copy.deepcopy(b)
        bad['index_1'] = [4, 5, 6]
        with self.assertRaises(ValueError):
            interpolate_cell(a, bad, 0.5)

    def test_group_reordering_uses_condition_not_position(self):
        a = {'leakage_power': [{'when': 'A', 'value': 1.0}, {'when': '!A', 'value': 2.0}]}
        b = {'leakage_power': [{'when': '!A', 'value': 4.0}, {'when': 'A', 'value': 3.0}]}
        self.assertEqual(interpolate_cell(a, b, 0.5)['leakage_power'],
                         [{'when': 'A', 'value': 2.0}, {'when': '!A', 'value': 3.0}])
        b['leakage_power'][1]['when'] = 'CLK'
        with self.assertRaises(ValueError):
            interpolate_cell(a, b, 0.5)

    def test_rotation_maps_temperature_to_correct_grid_cell(self):
        path = Path(__file__).resolve().parents[1]/'examples/layered_two_chiplets.json'
        raw = load_case(path).input_data
        grid = np.arange(16*24).reshape(16, 24).astype(float)
        for angle in (0, 90, 180, 270):
            case_data = copy.deepcopy(raw)
            case_data['chiplets'][1]['rotation_deg'] = angle
            case = parse_case(case_data)
            value, position = sample_instance_temperature(case, grid, 'rx', [0.25, 0.25])
            die = case.dies[1]
            x, y = die.point(0.25, 0.25)
            self.assertEqual(value, grid[int(y/0.5), int(x/0.5)])
            self.assertEqual(position['grid_index_xy'], [int(x/0.5), int(y/0.5)])
        case = load_case(path)
        with self.assertRaises(ValueError):
            sample_instance_temperature(case, grid, 'rx', [3, 0])
        with self.assertRaises(ValueError):
            sample_instance_temperature(case, np.full_like(grid, np.nan), 'rx', [0.25, 0.25])
        # Rotated origin must sample the die side of the high boundary.
        _, position = sample_instance_temperature(case, grid, 'rx', [0, 0])
        self.assertEqual(position['grid_index_xy'], [19, 7])

    def test_real_opensta_electrical_violation_headers_rejected(self):
        links = [{'kind': kind, 'assumed_c_pf': 1.0} for kind in ('data', 'clock')]
        prefix = 'Wire capacitance: 1\nWire capacitance: 1\n'
        suffix = 'Startpoint: tx_reg\nslack (VIOLATED)\nLANE_SLACK_max -1\nLANE_SLACK_min 2\n'
        # Negative timing slack is a valid analysis result, not a parser error.
        self.assertEqual(parse_sta_log(prefix+suffix, links)[0]['max'], '-1')
        for header in ('max slew', 'max capacitance', 'max_slew', 'max_capacitance'):
            with self.assertRaisesRegex(ValueError, 'electrical'):
                parse_sta_log(prefix+header+'\npad 1.00 1.84 -0.84 (VIOLATED)\n'+suffix, links)
        with self.assertRaises(ValueError):
            parse_sta_log(prefix+suffix+'Warning: unknown port DM\n', links)

    def test_gf_json_types_preserve_numeric_tables_and_logic(self):
        body = normalize_gf_json({'pin D': {'capacitance': '0.001', 'function': 'D',
                                          'table t': {'index_1': [1, 2], 'values': [[3, 4]]}}})
        self.assertEqual(body['pin,D']['capacitance'], 0.001)
        self.assertEqual(body['pin,D']['function'], 'D')
        self.assertEqual(body['pin,D']['table,t']['values'], [[3, 4]])


if __name__ == '__main__':
    unittest.main()
