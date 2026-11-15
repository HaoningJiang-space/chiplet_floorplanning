from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from workload_leverage import BOOST, budget_power, is_compute, regret, scenarios, verdict  # noqa: E402


class WorkloadLeverageTest(unittest.TestCase):
    def test_freed_power_boosts_only_active_compute_up_to_the_cap(self):
        names = ('CPU1_0', 'GPU_0', 'GPU_1', 'HBM_0', 'MEMS_0')
        nominal = np.array([100., 300., 300., 25., 3.])
        odd = scenarios(names)['odd_idle']
        self.assertEqual(odd.tolist(), [1., 1., .2, 1., 1.])  # only GPU has two dies of its kind
        power = budget_power(nominal, odd, is_compute(names))
        self.assertEqual(power[[2, 3, 4]].tolist(), [60., 25., 3.])
        # 240 W freed but only 0.5 x (100 + 300) = 200 W of room: both active compute dies hit the cap.
        self.assertTrue(np.allclose(power[:2], BOOST*nominal[:2]))
        self.assertAlmostEqual(power.sum(), nominal.sum() - 40.)
        partial = budget_power(nominal, np.array([1., 1., 1., .2, 1.]), is_compute(names))
        self.assertAlmostEqual(partial.sum(), nominal.sum())  # 20 W fits, shared in proportion to nominal
        self.assertAlmostEqual(partial[1]/partial[0], 3.)

    def test_scenarios_that_idle_all_compute_or_change_nothing_are_left_out(self):
        self.assertEqual(sorted(scenarios(('CPU2_0', 'CPU2_1', 'DRAM_0'))),
                         ['compute_half', 'even_idle', 'memory_idle', 'odd_idle'])
        self.assertEqual(sorted(scenarios(('Virtuvian_0', 'HBM_0', 'Nimbus_0'))), ['compute_half', 'memory_idle'])

    def test_regret_is_measured_within_the_length_cap(self):
        length = [10., 12., 30.]
        row = regret(length, [100., 99., 90.], base_best=0)
        self.assertEqual((row['best'], row['regret_k'], row['lever_k']), (1, 1., 1.))
        self.assertEqual(verdict([dict(a=row)]*3), 'worthwhile')
        self.assertEqual(verdict([dict(a=row)]*2), 'uncertain')
        self.assertEqual(verdict([dict(a=regret(length, [100., 99.8, 90.], 0))]), 'degenerate')


if __name__ == '__main__':
    unittest.main()
