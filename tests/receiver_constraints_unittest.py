import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from receiver_constraints import Constraint, classify, edge_metrics, receivers  # noqa: E402
from characterize_receiver import EDGE_NS, clock_to_q, ramp  # noqa: E402


def liberty(offset):
    table = lambda base: {'index_1': [0.01, 0.5, 1.5], 'index_2': [0.01, 0.5, 1.5],
                          'values': [[base + offset + i + 10*j for j in range(3)] for i in range(3)]}
    return {'pin,D': {'timing': [{'timing_type': kind, 'rise_constraint,vio_3_3_1': table(0.),
                                  'fall_constraint,vio_3_3_1': table(100.)}
                                 for kind in ('setup_rising', 'hold_rising')]}}


class ReceiverConstraintTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.paths = []
        for name, offset in (('t25.json', 0.), ('t100.json', 7.5)):
            path = Path(self.folder.name)/name
            path.write_text(json.dumps(liberty(offset)))
            self.paths.append(path)
        self.constraint = Constraint(*self.paths)

    def tearDown(self):
        self.folder.cleanup()

    def test_grid_points_bilinear_slews_and_linear_temperature(self):
        self.assertEqual(self.constraint('setup', 'rise', 0.5, 1.5, 25.), 1 + 20)
        self.assertEqual(self.constraint('hold', 'fall', 0.01, 0.01, 100.), 107.5)
        # Midway in both slews and temperature: plane through the grid plus half the 7.5 offset.
        self.assertAlmostEqual(self.constraint('setup', 'rise', 0.255, 0.255, 62.5), 0.5 + 5 + 3.75)

    def test_no_extrapolation(self):
        with self.assertRaises(ValueError):
            self.constraint('setup', 'rise', 2.0, 0.1, 25.)
        with self.assertRaises(ValueError):
            self.constraint('setup', 'rise', 0.1, 0.1, 120.)

    def test_ramp_slew_and_midpoint(self):
        t = np.linspace(0, 30, 30001)
        v = np.clip((t - 21)/0.5, 0, 1)*1.8  # 0->1.8 V over 0.5 ns from 21 ns
        middle, slew = edge_metrics(t, v, 21., True)
        self.assertAlmostEqual(middle, 21.25, places=6)
        self.assertAlmostEqual(slew, 0.3, places=6)  # 20-80% of a 0.5 ns ramp

    def test_receivers_read_local_or_default_temperature(self):
        deck = '.options device temp=25\n' + ''.join(
            f'X_rx_{g}_{l} capture_{g} wire_{g}_{l} 0 0 vdd vdd q sky130_fd_sc_hd__dfxtp_1'
            + (' cell_temp_c=64.5\n' if g else '\n') for g in range(2) for l in range(4))
        rx = receivers(deck)
        self.assertEqual(rx['0_1'], ('capture_0', 'wire_0_1', 25.))
        self.assertEqual(rx['1_3'][2], 64.5)

    def test_characterization_ramp_has_declared_slew_and_midpoint(self):
        (t0, v0), (t1, v1) = ramp(15., 0.3, False)
        t = np.linspace(t0 - 1, t1 + 1, 40001)
        v = np.interp(t, [t0, t1], [v0, v1])
        middle, slew = edge_metrics(t, v, t0, False)
        self.assertAlmostEqual(middle, 15., places=6)
        self.assertAlmostEqual(slew, 0.3, places=6)

    def test_clock_to_q_rejects_invalid_and_glitching_outputs(self):
        # Review of 81bb3f0: NaN waves passed (NaN comparisons are false) and an early glitch
        # was read as the output time.
        t = np.linspace(0, 30, 30001)
        clk = np.interp(t, [EDGE_NS[1] - .05, EDGE_NS[1] + .05], [0, 1.8])
        edge = lambda at: np.interp(t, [at - .01, at + .01], [0, 1.8])
        clean = edge(EDGE_NS[1] + .1)
        self.assertAlmostEqual(clock_to_q(t, clk, clean, True), .1, places=6)
        nan = clean.copy()
        nan[t >= EDGE_NS[1] + 4] = np.nan
        self.assertIsNone(clock_to_q(t, clk, nan, True))
        glitch = np.where((t > EDGE_NS[1] + .09) & (t < EDGE_NS[1] + .3), 1.8, edge(EDGE_NS[1] + 1.))
        self.assertAlmostEqual(clock_to_q(t, clk, glitch, True), 1., places=6)

    def test_screen_matches_original_rule(self):
        self.assertEqual(classify([3., 3.1], [2.9, 3.0], True, .01)['ordering'], 'stable')
        self.assertEqual(classify([3., 3.1], [-2.9, -3.0], True, .01)['ordering'], 'changed')
        self.assertEqual(classify([.05, .2], [3., 3.], True, .01)['ordering'], 'unresolved')
        self.assertEqual(classify([3., 3.], [3., 3.], True, .01)['interaction_status'], 'no_resolved_interaction')


if __name__ == '__main__':
    unittest.main()
