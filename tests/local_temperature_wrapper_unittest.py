import unittest
from pathlib import Path
import sys
import json
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))

from probe_core_local_temperature import instrument, observe_case


class TemperatureWrapperTest(unittest.TestCase):
    def test_bad_header_and_missing_wave_have_structured_failure(self):
        for content in (None, 'TIME,V(wrong)\n0,0\n1,1\n',
                        'TIME,V(VIN),V(OUT1),V(OUT2),I(VDD1),I(VDD2),I(VIN)\n0,nan,0,0,0,0,0\n1,0,0,0,0,0,0\n'):
            with self.subTest(content=content), TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root/'deck.cir').write_text('test circuit')
                (root/'xyce.log').write_text('completed process')
                if content is not None:
                    (root/'deck.cir.csv').write_text(content)
                report = dict(complete=False, cases=[])
                with self.assertRaises((ValueError, OSError)):
                    observe_case(report, root, root, 'case', 'inv_1')
                saved = json.loads((root/'report.json').read_text())
                self.assertFalse(saved['complete'])
                self.assertFalse(saved['forwarding_controls_pass'])
                self.assertEqual(saved['cases'][0]['status'], 'invalid_observation')
                self.assertIn('deck.cir', saved['cases'][0]['artifacts_sha256'])
    def test_only_temperature_forwarding_is_added(self):
        original = ('.subckt inv a y vdd gnd\n'
                    'X0 y a gnd gnd sky130_fd_pr__nfet_01v8 w=.65 l=.15\n.ends\n')
        changed, count = instrument(original)
        self.assertEqual(count, 1)
        self.assertEqual(changed.replace(' params: cell_temp_c=25', '')
                         .replace(' device_temp_c={cell_temp_c}', ''), original)

    def test_unknown_primitive_cannot_silently_keep_global_temperature(self):
        with self.assertRaisesRegex(ValueError, 'unhandled primitive'):
            instrument('.subckt a x y\nX0 x y unknown\n.ends\n')

    def test_repeated_instrumentation_rejected(self):
        first, _ = instrument('.subckt fet d g s b\nM1 d g s b nm l=1u w=1u\n.ends\n', True)
        with self.assertRaisesRegex(ValueError, 'already present'):
            instrument(first, True)

    def test_multiple_primitive_devices_rejected(self):
        with self.assertRaisesRegex(ValueError, 'topology'):
            instrument('.subckt a d g s b\nM1 d g s b nm\nM2 d g s b nm\n.ends\n', True)


if __name__ == '__main__':
    unittest.main()
