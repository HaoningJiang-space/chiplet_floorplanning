from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_integrated_transistors import build_fabric


class TransistorFabricTest(unittest.TestCase):
    def fixture(self):
        text = '\n'.join(f'thermal_b{i} b{i} (.A(in_{i}), .X(out_{i}));' for i in range(32))
        receipt = dict(models={f'b{i}': dict(cell=f'thermal_b{i}', source_files={'sky_buf_8_tt_025C_1v80.json': 'test'}) for i in range(32)},
            rc={'shared': dict(source_pin='b0:X', source_index=0, sink_pins=['b1:A', 'b2:A'],
                sink_indices=[1, 2], node_parasitic_pf=[.1, .2, .3], total_sink_pin_pf=.7,
                conductors=[dict(a=0, b=1, resistance_ohm=2), dict(a=1, b=2, resistance_ohm=3)])})
        return text, receipt

    def test_shared_wire_once_and_no_liberty_pin_cap_double_count(self):
        text, receipt = self.fixture()
        elements, nodes = build_fabric(text, receipt)
        self.assertEqual(sum(e.startswith('R_') for e in elements), 2)
        self.assertEqual(sum(e.startswith('C_') for e in elements), 3)
        self.assertAlmostEqual(sum(float(e.split()[-1][:-1]) for e in elements if e.startswith('C_')), .6)
        self.assertEqual(nodes['b0:X'], 'wire_shared_0')
        self.assertEqual(nodes['b2:A'], 'wire_shared_2')
        self.assertEqual(sum(e.startswith('X_') for e in elements), 32)

    def test_missing_cell_and_wrong_source_identity_rejected(self):
        text, receipt = self.fixture()
        with self.assertRaises(ValueError):
            build_fabric('\n'.join(text.splitlines()[1:]), receipt)
        receipt['models']['b0']['source_files'] = {'sky_inv_1_tt_025C_1v80.json': 'test'}
        with self.assertRaisesRegex(ValueError, 'identity'):
            build_fabric(text, receipt)

    def test_nonpassive_conductor_rejected(self):
        text, receipt = self.fixture()
        receipt['rc']['shared']['conductors'][0]['resistance_ohm'] = 0
        with self.assertRaisesRegex(ValueError, 'resistance'):
            build_fabric(text, receipt)


if __name__ == '__main__':
    unittest.main()
