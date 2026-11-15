from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from workload_search import llm_power, targets  # noqa: E402


class WorkloadSearchTest(unittest.TestCase):
    def test_llm_power_meets_the_package_share_with_one_compute_activity(self):
        names = ('CPU1_0', 'GPU_0', 'GPU_1', 'HBM_0', 'HBM_1', 'HBM_2')
        nominal = np.array([105., 300., 300., 25., 25., 25.])
        power, x = llm_power(names, nominal, total=.55, memory=1.)
        self.assertAlmostEqual(power.sum(), .55*780)
        self.assertTrue(np.allclose(power[:3], x*nominal[:3]) and np.allclose(power[3:], 25.))
        power, x = llm_power(names, nominal, total=.9, memory=.5)
        self.assertAlmostEqual(power.sum(), .9*780)
        self.assertAlmostEqual(power[3], 12.5)
        _, x = llm_power(names, nominal, total=1.2, memory=1.)
        self.assertEqual(x, 1.)  # no boost: clipped

    def test_targets_cover_declared_controls_and_llm(self):
        case10 = ('CPU1_0', 'CPU1_1', 'CPU2_0', 'GPU_0', 'GPU_1', 'IODie_0')
        self.assertEqual(sorted(targets(case10, 10)), ['budget/compute_half', 'budget/cpu_idle'])
        case1 = ('CPU1_0', 'GPU_0', 'GPU_1', 'HBM_0')
        self.assertEqual(sorted(targets(case1, 1)), ['llm/decode_hbm_full', 'llm/decode_hbm_half', 'llm/prefill'])


if __name__ == '__main__':
    unittest.main()
