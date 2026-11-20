import unittest

import numpy as np
from scipy.sparse import diags, kronsum

from chiplet_floorplanning.placement.transfer_bound import ContactPlane, InsulatedSheet, ThermalMargin
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet, LATERAL_W_K, VERTICAL_MM2_K_W
from chiplet_floorplanning.placement.observer_search import search_observers


class TransferBoundTest(unittest.TestCase):
    def test_range_for_distributed_sinks_and_equality_at_one_sink(self):
        def line(n):
            return diags((-np.ones(n-1), [1, *([2]*(n-2)), 1], -np.ones(n-1)), (-1, 0, 1))

        shape = (3, 4)
        lateral = .4 * kronsum(line(4), line(3)).toarray()
        power = np.zeros(shape)
        power[0, 1], power[1, 2] = 3., 2.
        after = power.copy()
        after[0, 1], after[2, 3] = 0., 3.
        transfer = InsulatedSheet(shape, .4, .7).transfer(after-power)
        np.testing.assert_allclose(lateral @ transfer.bare_k.ravel(), (after-power).ravel(), atol=1e-13)
        for sinks in ((1.,), (.01, 4.), (2., 1., .1)):
            sink = np.zeros(12)
            sink[:len(sinks)] = sinks
            matrix = lateral+np.diag(sink)
            def field(p):
                return np.linalg.solve(matrix, p.ravel()).reshape(shape) + .7*p
            old, new = field(power), field(after)
            gain = old.max()-new.max()
            window = ThermalMargin(old, sink).window(transfer, after>0)
            self.assertLessEqual(window.gain_low_k, gain+1e-10)
            self.assertGreaterEqual(window.gain_high_k, gain-1e-10)
            self.assertGreaterEqual(window.rise_upper_k, np.max(new-old)-1e-10)
            if len(sinks) == 1:
                self.assertAlmostEqual(window.gain_low_k, window.gain_high_k)

    def test_power_change_requires_a_different_reference_model(self):
        with self.assertRaisesRegex(ValueError, "conserve watts"):
            InsulatedSheet((2, 3), .4, 0.).transfer(np.ones((2, 3)))

    def test_lifted_coordinate_residual_encloses_the_whole_board(self):
        from types import SimpleNamespace
        sheet = CooledSheet(SimpleNamespace(carrier_um=(20000, 20000)), np.array([101.4, 92.8]))
        q = np.zeros((100, 100))
        q[44, 39], q[70, 80] = -4., 4.
        start = np.maximum(-q, 0)
        start[39, 30] += 3.
        initial, final = (sheet.temperatures(x) for x in (start, start+q))
        transfer = InsulatedSheet(q.shape, LATERAL_W_K, VERTICAL_MM2_K_W).transfer(q)
        bounds = ThermalMargin(initial, sheet.sink).window(transfer, start+q>0, ContactPlane(sheet))
        self.assertGreaterEqual(bounds.rise_upper_k+1e-8, (final-initial).max())
        gain = initial.max()-final.max()
        self.assertLessEqual(bounds.gain_low_k, gain+1e-8)
        self.assertGreaterEqual(bounds.gain_high_k, gain-1e-8)

    def test_lazy_bound_reorders_contenders_without_hiding_cost_ties(self):
        visited = []
        def verify(i):
            return (0., -1., 2., 2.)[i], i
        def tighten(i):
            visited.append(i)
            return (0., -1., 2., 2.)[i]
        result = search_observers([0., 5., 3., 2.], [3., 2., 3., 1.], verify, tighten=tighten)
        self.assertEqual(result.best, 3)
        self.assertNotIn(1, result.checked)
        self.assertEqual(sorted(visited), [1, 2, 3])
