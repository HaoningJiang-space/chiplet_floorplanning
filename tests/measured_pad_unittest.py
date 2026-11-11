import sys
import tempfile
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.measured_pad import read_mdm, compare


MDM = '''! VERSION = 6.00
BEGIN_HEADER
ICCAP_INPUTS
VG V B GROUND SMU4 0.001 LIN 1 0 -1 2 -1
VS V E GROUND SMU2 0.1 CON 0
VB V C GROUND SMU3 0.1 CON 0
VD V S GROUND SMU1 0.1 CON -1
ICCAP_OUTPUTS
IG I B GROUND SMU4 B
ID I S GROUND SMU1 B
IB I C GROUND SMU3 B
END_HEADER
BEGIN_DB
ICCAP_VAR VS 0
ICCAP_VAR VB 0
ICCAP_VAR VD -1
#VG IG ID IB
0 0 -1e-9 0
-1 0 -1e-3 0
END_DB
'''


class MeasuredPadTest(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'example.mdm'
            p.write_text(text)
            return read_mdm(p)

    def test_signed_pfet_named_columns_and_fixed_bias(self):
        c = self.parse(MDM)[0]
        np.testing.assert_equal(c['columns']['ID'], [-1e-9, -1e-3])
        self.assertEqual(c['fixed']['VD'], -1)

    def test_truncated_and_duplicate_bias_curves_rejected(self):
        for text in [MDM.replace('-1 0 -1e-3 0\n', ''),
                     MDM + MDM[MDM.index('BEGIN_DB'):],
                     MDM.replace('ICCAP_VAR VD -1', 'ICCAP_VAR VD -2')]:
            with self.assertRaises(ValueError):
                self.parse(text)

    def test_independent_four_terminal_kcl_and_power(self):
        c = self.parse(MDM)[0]
        a = np.array([[0, 1e-9, 0, -1e-9, 0, -1, 0, 0, 0],
                      [-1, .001, 0, -.001, 0, -1, -1, 0, 0]])
        r = compare(c, a)
        self.assertEqual(r['id_rmse_a'], 0)
        self.assertTrue(r['model_kcl_screen'])
        self.assertTrue(r['model_power_screen'])
        a[1, 3] = 0
        self.assertFalse(compare(c, a)['model_kcl_screen'])
        a[1, 1:5] *= -1
        self.assertFalse(compare(c, a)['model_power_screen'])

    def test_wrong_voltage_plane_rejected(self):
        c = self.parse(MDM)[0]
        a = np.zeros((2, 9))
        a[1, 0] = -1
        with self.assertRaisesRegex(ValueError, 'terminal voltages'):
            compare(c, a)


if __name__ == '__main__':
    unittest.main()
