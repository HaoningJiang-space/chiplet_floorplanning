from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.spice_waveform import read_real_binary


class BinaryWaveformTest(unittest.TestCase):
    def content(self):
        return (b'Title: control\nPlotname: Transient Analysis\nFlags: real\n'
                b'No. Variables: 2\nNo. Points: 2\nVariables:\n'
                b'0 time time\n1 v(n) voltage\nBinary:\n' + struct.pack('<4d', 0., 0., 1e-12, 3.3))

    def test_known_real_transient(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.raw'
            path.write_bytes(self.content())
            np.testing.assert_array_equal(read_real_binary(path, ['time', 'v(n)']), [[0., 0.], [1e-12, 3.3]])

    def test_partial_or_extra_payload_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.raw'
            for content in (self.content()[:-1], self.content()+b'x'):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    read_real_binary(path, ['time', 'v(n)'])

    def test_wrong_columns_and_complex_data_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.raw'
            path.write_bytes(self.content())
            with self.assertRaises(ValueError):
                read_real_binary(path, ['time', 'v(other)'])
            path.write_bytes(self.content().replace(b'Flags: real', b'Flags: complex'))
            with self.assertRaises(ValueError):
                read_real_binary(path, ['time', 'v(n)'])


if __name__ == '__main__':
    unittest.main()
