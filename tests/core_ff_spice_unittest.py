from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_core_ff_spice import measure


class SequentialMeasurementTest(unittest.TestCase):
    def wave(self):
        t = np.linspace(0, 18, 18001)
        data = np.zeros((len(t), 7))
        data[:, 0] = t*1e-9
        def ramp(start):
            return np.clip((t-start)/.2, 0, 1)*1.8
        data[:, 1] = sum(ramp(start)-ramp(start+2) for start in (1, 7, 13))
        data[:, 3] = ramp(7.3)-ramp(13.3)
        return data

    def test_independent_known_clock_to_q(self):
        result = measure(self.wave())
        for edge in ('rise', 'fall'):
            self.assertAlmostEqual(result[edge+'_delay_ns'], .3)
            self.assertAlmostEqual(result[edge+'_slew_ns'], .12)

    def test_capture_failure_rejected(self):
        data = self.wave()
        data[:, 3] = 0
        with self.assertRaisesRegex(ValueError, 'capture'):
            measure(data)

    def test_multiple_crossings_rejected(self):
        data = self.wave()
        data[7500:7600, 3] = 0
        with self.assertRaisesRegex(ValueError, 'crossing'):
            measure(data)

    def test_truncation_and_reversed_time_rejected(self):
        for data in (self.wave()[:-100], self.wave()[::-1]):
            with self.assertRaises(ValueError):
                measure(data)


if __name__ == '__main__':
    unittest.main()
