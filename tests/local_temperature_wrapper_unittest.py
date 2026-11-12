import unittest

from probe_core_local_temperature import instrument


class TemperatureWrapperTest(unittest.TestCase):
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
