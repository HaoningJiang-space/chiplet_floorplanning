from dataclasses import replace
from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Problem, sample_legal, solve  # noqa: E402
from intra_die_orientation import half_powers, half_responses, orient, peak_c, split_case, verdict  # noqa: E402


class IntraDieOrientationTest(unittest.TestCase):
    def setUp(self):
        problem = Problem.from_imported(synthetic_case(random.Random(29), chips=4, nets=30))
        self.problem = replace(problem, names=('GPU_0', 'CPU2_0', 'HBM_0', 'GPU_1'))
        self.layout = sample_legal(self.problem, 1000, np.random.default_rng(8))
        self.responses = half_responses(self.problem, self.layout, 1000, 24)

    def test_superposed_field_matches_a_direct_solve(self):
        flipped = np.array([True, False, False, True])
        powers = half_powers(self.problem, 0.8, flipped)
        self.assertAlmostEqual(powers[0, 0], 0.2*self.problem.power_w[0])
        self.assertEqual(powers[2, 0], powers[2, 1])                      # memory stays uniform
        direct = solve(split_case(self.problem, self.layout, 1000, 24, powers))[0]['peak_power_layer_c']
        self.assertAlmostEqual(peak_c(self.responses, powers), direct, places=8)

    def test_greedy_orientation_brackets_the_original(self):
        original = peak_c(self.responses, half_powers(self.problem, 0.8, np.zeros(4, bool)))
        low, flips = orient(self.problem, self.responses, 0.8, +1)
        high, _ = orient(self.problem, self.responses, 0.8, -1)
        self.assertLessEqual(low, original + 1e-12)
        self.assertGreaterEqual(high, original - 1e-12)
        self.assertFalse(flips[2])                                         # memory is never flipped

    def test_verdict_rules(self):
        row = lambda gain, regret: dict(by_share={'0.8': dict(orientation_gain_k=gain, layout_regret_k=regret)})
        self.assertEqual(verdict([row(3, 0)]*2 + [row(0, 2)] + [row(0, 0)]*7), 'calibrate')
        self.assertEqual(verdict([row(.9, .9)]*10), 'stop')
        self.assertEqual(verdict([row(3, 0)]*2 + [row(0, 0)]*8), 'uncertain')


if __name__ == '__main__':
    unittest.main()
