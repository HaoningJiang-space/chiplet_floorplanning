import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from receiver_constraints import Constraint, classify, edge_metrics, receivers  # noqa: E402


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

    def test_screen_matches_original_rule(self):
        self.assertEqual(classify([3., 3.1], [2.9, 3.0], True, .01)['ordering'], 'stable')
        self.assertEqual(classify([3., 3.1], [-2.9, -3.0], True, .01)['ordering'], 'changed')
        self.assertEqual(classify([.05, .2], [3., 3.], True, .01)['ordering'], 'unresolved')
        self.assertEqual(classify([3., 3.], [3., 3.], True, .01)['interaction_status'], 'no_resolved_interaction')


if __name__ == '__main__':
    unittest.main()
