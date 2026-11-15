from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from cold_plate_tradeoff import FLOWS_LPM, fit, needed_flow, summarise, verdict  # noqa: E402

Q = np.array(FLOWS_LPM)


class ColdPlateTradeoffTest(unittest.TestCase):
    def test_fit_recovers_the_inverse_flow_law_and_the_needed_flow(self):
        alpha, beta, error = fit(80. + 6./Q)
        self.assertAlmostEqual(float(alpha), 80.)
        self.assertAlmostEqual(float(beta), 6.)
        self.assertLess(float(error), 1e-9)
        self.assertAlmostEqual(float(needed_flow(alpha, beta, 86.)), 1.)
        self.assertEqual(float(needed_flow(alpha, beta, 79.)), np.inf)  # below the infinite-flow limit

    def test_longer_layout_with_the_right_direction_saves_pumping(self):
        # Layout 0 is shortest; layout 1 (20% longer) is cooler and better along -x; layout 2 lies between 1.25 and 1.5 Lmin.
        length = [10., 12., 14.]
        fixed = np.array([90., 88., 70.])
        plate = np.empty((3, 4, 3))
        plate[0] = 90. + 8./Q
        plate[1] = 88. + 8./Q
        plate[1, 1] = 87. + 4./Q
        plate[2] = 60. + 1./Q
        s = summarise(length, fixed, plate)
        self.assertEqual(s['blind_layout'], 1)
        self.assertEqual(s['caps']['1.25']['direction'], '-x')
        self.assertAlmostEqual(s['regret_k']['1.0'], 0.)
        self.assertAlmostEqual(s['target_c'], 91.)
        self.assertAlmostEqual(s['caps']['1.0']['flow_lpm'], 8.)
        self.assertAlmostEqual(s['caps']['1.25']['flow_lpm'], 1.)
        self.assertAlmostEqual(s['pump_ratio_short_vs_125'], 512.)
        self.assertEqual(s['caps']['1.5']['layout'], 2)

    def test_verdict_separates_direction_coupling_from_the_tradeoff(self):
        case = dict(regret_k={'1.0': 1.2}, pump_ratio_short_vs_125=3.)
        self.assertEqual(verdict([case]*3), dict(direction_coupling='worthwhile', length_pumping_tradeoff=True))
        quiet = dict(regret_k={'1.0': .1}, pump_ratio_short_vs_125=None)
        self.assertEqual(verdict([quiet]*3), dict(direction_coupling='degenerate', length_pumping_tradeoff=True))


if __name__ == '__main__':
    unittest.main()
