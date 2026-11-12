import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from prepare_tap_thermal import check_partition, thermal_margin, thermal_witness
from freeze_tap_geometry import verify

class TapThermalTest(unittest.TestCase):
    def check_text(self,text):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'case.flp';p.write_text(text)
            return check_partition(p,1)

    def test_overlap_cannot_hide_behind_correct_total_area(self):
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            self.check_text('a 0.5 1 0 0\nb 0.5 1 0.25 0\n')

    def test_gap_and_outside_are_rejected(self):
        for text in ('a 0.9 1 0 0\n','a 1 1 0.1 0\n'):
            with self.assertRaises(ValueError):self.check_text(text)
        self.assertEqual(self.check_text('a 0.5 1 0 0\nb 0.5 1 0.5 0\n')['area_m2'],1)

    def test_thermal_border_is_a_stricter_separate_domain(self):
        root=Path(__file__).resolve().parents[1]
        entries=json.loads((root/'docs/evidence/tap-geometry-domains.json').read_text())['cases']
        for entry in entries:
            d=entry['domain']
            verify(d,entry['witness']['placement'])
            p=thermal_witness(d)
            verify(d,p)
            self.assertTrue(all(thermal_margin(d,v) for v in p))
        ascend=entries[0]
        self.assertFalse(all(thermal_margin(ascend['domain'],v) for v in ascend['witness']['placement']))

if __name__=='__main__':unittest.main()
