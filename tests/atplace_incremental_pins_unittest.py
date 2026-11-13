from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS
from import_atplace_cases import parse_case
from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import repair as reference


class IncidentPinsTest(unittest.TestCase):
    def setUp(self):
        self.source = parse_case('test', BLOCKS, POWER, NETS)
        self.poses = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=180),
                      dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=90)]

    def equivalent(self):
        before = deepcopy(self.poses)
        expected = reference(self.source, self.poses, 1000)
        result = IncidentPinRepair(self.source, 1000).repair(self.poses)
        self.assertEqual(self.poses, before)
        self.assertEqual(result['placement'], expected['placement'])
        self.assertEqual(result['metric'], expected['metric'])
        self.assertEqual(result['trials'], expected['trials'])
        return result

    def test_different_shapes_and_decimal_offsets_match_full_reference(self):
        self.source['nets'][0]['pins'][0]['offset_x_um_decimal'] = '999.12345'
        self.equivalent()

    def test_same_die_net_rotates_both_endpoints_once(self):
        net = deepcopy(self.source['nets'][0])
        net['id'] = 1
        net['pins'][1]['chiplet'] = 'a'
        self.source['nets'].append(net)
        result = self.equivalent()
        # Initial 2, one a trial *2, three b trials *1, final full 2.
        self.assertEqual(result['effort']['net_length_evaluations'], 9)

    def test_ties_disconnected_die_and_repeated_nets(self):
        for p in self.source['nets'][0]['pins']:
            p['chiplet'] = 'a'
            p['offset_x_um_decimal'] = p['offset_y_um_decimal'] = '0'
        self.source['nets'].append(dict(deepcopy(self.source['nets'][0]), id=1))
        result = self.equivalent()
        self.assertEqual(result['placement'], self.poses)


if __name__ == '__main__':
    unittest.main()
