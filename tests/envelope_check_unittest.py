from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from envelope_check import score  # noqa: E402


class EnvelopeCheckTest(unittest.TestCase):
    def test_score_reports_the_regret_of_the_predicted_pick(self):
        fv = np.array([80., 82., 85.])
        out = score(np.array([91., 90., 95.]), fv)        # picks the second layout: 2 K worse than the best
        self.assertAlmostEqual(out['regret_k'], 2.0)
        self.assertAlmostEqual(out['spearman'], 0.5)
        self.assertAlmostEqual(out['max_abs_k'], 11.0)


if __name__ == '__main__':
    unittest.main()
