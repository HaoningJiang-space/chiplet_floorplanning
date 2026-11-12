"""Uniform controls must keep the circuit and stimuli fixed."""
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_xyce_uniform import export_control


class UniformFabricTest(unittest.TestCase):
    def setUp(self):
        self.elements = [f'X_cell{i} a b vdd gnd inv' for i in range(32)] + [
            'R_wire a b 12.5', 'C_wire b 0 2e-15']
        self.lines = ['circuit', '.lib "original/models.spice" tt',
                      '.include "original/inv_1.spice"', '.options device temp=25',
                      'VDD vdd 0 1.8', 'VIN a 0 PULSE(0 1.8 1n .1n .1n 4n 10n)',
                      *self.elements, '.tran 2.5p 60n', '.end']

    def export(self, local, temperature=65):
        return export_control(self.lines, self.elements, temperature, local,
                              Path('models'), Path('copies')).splitlines()

    def test_global_changes_only_ambient(self):
        expected = [s.replace('temp=25', 'temp=65') for s in self.lines]
        self.assertEqual(self.export(False), expected)

    def test_local_all_instances_same_temperature_and_rc_unchanged(self):
        for temperature in (25, 65):
            with self.subTest(temperature=temperature):
                lines = self.export(True, temperature)
                cells = [s for s in lines if s.startswith('X_')]
                self.assertEqual(len(cells), 32)
                suffix = f' cell_temp_c={temperature}'
                self.assertTrue(all(s.endswith(suffix) for s in cells))
                self.assertEqual(Counter(s.removesuffix(suffix) for s in cells),
                                 Counter(self.elements[:32]))
                self.assertEqual([s for s in lines if s.startswith(('R_', 'C_'))],
                                 self.elements[32:])
                for line in self.lines:
                    if line.startswith(('VDD ', 'VIN ', '.tran ', '.options ')):
                        self.assertIn(line, lines)
                self.assertEqual(lines[-1], '.end')

    def test_modified_or_duplicated_physical_element_rejected(self):
        for extra in ('R_wire a b 13', self.elements[0]):
            with self.subTest(extra=extra):
                self.lines.insert(-1, extra)
                with self.assertRaisesRegex(ValueError, 'verified complete circuit'):
                    self.export(True)
                self.lines.pop(-2)

    def test_conflicting_ambient_rejected(self):
        self.lines.insert(-1, '.options device temp=25')
        with self.assertRaisesRegex(ValueError, 'ambient'):
            self.export(True)


if __name__ == '__main__':
    unittest.main()
