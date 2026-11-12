from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from import_atplace_cases import parse_case, rotate_offset

BLOCKS = '''NumSoftRectangularBlocks : 0
NumHardRectilinearBlocks : 2
NumTerminals : 0
InterposerWidth : 10000
InterposerHeight : 10000
a hardrectilinear 4 (0, 0) (0, 2000) (4000, 2000) (4000, 0)
b hardrectilinear 4 (0, 0) (0, 1000) (1000, 1000) (1000, 0)
'''
POWER = 'a 2.5\nb 0\n'
NETS = '''NumNets : 1
NumPins : 2
NetDegree : 2
a B : %25 %-10
b B : %-50 %50
'''


class AtplaceImportTest(unittest.TestCase):
    def test_percent_units_and_quarter_turns(self):
        case = parse_case('test', BLOCKS, POWER, NETS)
        pin = case['nets'][0]['pins'][0]
        self.assertEqual((pin['offset_x_um_decimal'], pin['offset_y_um_decimal']), ('1000', '-200'))
        self.assertEqual(rotate_offset('1000', '-200', 90), ('200', '1000'))
        self.assertEqual(rotate_offset('1000', '-200', 180), ('-1000', '200'))
        self.assertEqual(rotate_offset('1000', '-200', 270), ('-200', '-1000'))
        self.assertIsNone(case['package_model'])
        self.assertIsNone(case['placement_grid_um'])

    def test_bad_net_records_and_counts_rejected(self):
        for nets in (NETS.replace('NumPins : 2', 'NumPins : 3'), NETS.replace('a B', 'c B'),
                     NETS.replace('%25', '%51'), NETS.replace('%25', '25'),
                     NETS.replace('NetDegree : 2', 'NetDegree : 3'), NETS.rsplit('\n', 2)[0]):
            with self.subTest(nets=nets), self.assertRaises(ValueError):
                parse_case('test', BLOCKS, POWER, nets)

    def test_bad_power_and_geometry_rejected(self):
        for power in ('a 1', 'a 1\na 2\nb 1', 'a NaN\nb 1', 'a -1\nb 1', 'a 1\nc 2'):
            with self.subTest(power=power), self.assertRaises(ValueError):
                parse_case('test', BLOCKS, power, NETS)
        with self.assertRaises(ValueError):
            parse_case('test', BLOCKS.replace('(4000, 2000)', '(3999, 2000)'), POWER, NETS)


if __name__ == '__main__':
    unittest.main()
