from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from interface_margin import analyse, choice, cost  # noqa: E402


class InterfaceMarginTest(unittest.TestCase):
    def test_cost_is_the_critical_net(self):
        length, temp = np.array([[1., 4.], [3., 2.]]), np.full((2, 2), 25.)
        self.assertEqual(cost(length, temp, 1., 0.003).tolist(), [5., 4.])

    def test_short_hot_layout_loses_only_with_enough_temperature_weight(self):
        # Layout 0 is shorter but at 125 C; layout 1 is 5% longer and at 45 C.
        length, temp = np.array([[10.], [10.5]]), np.array([[125.], [45.]])
        self.assertEqual(choice(length, temp, 0., 0.)['verdict'], 'unchanged')
        self.assertEqual(choice(length, temp, 0., 1e-4)['verdict'], 'unchanged')
        hot = choice(length, temp, 0., 0.004)
        self.assertEqual((hot['verdict'], hot['actual_best'], hot['signoff_best']), ('changed', 1, 0))
        self.assertAlmostEqual(hot['advantage'], (14 - 11.34)/14)
        self.assertEqual(hot['recovery'][0], 0.)  # already at the signoff temperature

    def test_small_advantage_is_indistinguishable(self):
        length, temp = np.array([[10.], [10.05]]), np.array([[125.], [115.]])
        self.assertEqual(choice(length, temp, 0., 0.001)['verdict'], 'indistinguishable')

    def test_changed_case_is_refused_before_any_solve(self):
        # Review of d898800: pins do not enter the heat equation, so a case with moved pins
        # reproduced the frozen peaks and passed.
        with tempfile.TemporaryDirectory() as folder:
            case, summary = Path(folder)/'case.json', Path(folder)/'summary.json'
            case.write_text('{"nets": []}')
            summary.write_text(json.dumps(dict(case_sha256=sha256(b'frozen').hexdigest(), front=[])))
            with self.assertRaises(SystemExit):
                analyse(case, summary, Path(folder)/'missing.npz', 1)


if __name__ == '__main__':
    unittest.main()
