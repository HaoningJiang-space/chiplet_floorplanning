from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from chiplet_floorplanning.placement import Layout, Problem  # noqa: E402
from cooling_sweep import H_W_M2K, leverage, peak_c, verdict  # noqa: E402


class CoolingSweepTest(unittest.TestCase):
    def test_leverage_and_verdict(self):
        row = leverage(np.array([1.0, 1.2, 3.0]), np.array([95.0, 90.0, 85.0]))
        self.assertEqual((row['shortest_peak_c'], row['gap_k'], row['relative'], row['gap_125_k']), (95.0, 10.0, 0.2, 5.0))
        case = lambda strong, weak: {'5e+04': dict(gap_k=strong), '1.5e+03': dict(gap_k=weak)}
        self.assertEqual(verdict({k: case(1, 3) for k in range(10)} | {k: case(3, 3) for k in range(10, 12)}), 'confirmed')
        self.assertEqual(verdict({k: case(3, 3) for k in range(4)} | {k: case(1, 3) for k in range(4, 12)}), 'rejected')
        self.assertEqual(sorted(case(0, 0)), sorted(f'{h:.2g}' for h in H_W_M2K if h in (1500, 50000)))

    def test_spreading_two_hot_dies_helps_less_under_stronger_cooling(self):
        problem = Problem('two', ('a', 'b'), np.array([[8000., 8000.]]*2), np.array([60., 60.]), (60000., 20000.),
                          np.zeros((0, 2), int), np.zeros((0, 2, 2)))
        close = Layout(np.array([[25500., 10000.], [34500., 10000.]]), np.zeros(2, int))
        apart = Layout(np.array([[5000., 10000.], [55000., 10000.]]), np.zeros(2, int))
        gain = lambda h: peak_c((replace(problem, top_h_w_m2k=h), close, 0)) - peak_c((replace(problem, top_h_w_m2k=h), apart, 0))
        self.assertGreater(gain(1500.0), gain(50000.0))


if __name__ == '__main__':
    unittest.main()
