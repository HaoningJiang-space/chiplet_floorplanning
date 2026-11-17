from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from run_sizing import ASPECT, EXCLUDE, run_front, shapes, width_levels  # noqa: E402


class RunSizingTest(unittest.TestCase):
    def test_width_levels_respect_the_aspect_limit_and_the_widest_die(self):
        p = small_problem()
        levels = width_levels(p, 400.)
        self.assertGreaterEqual(levels.min(), max(np.sqrt(400/ASPECT), p.size_um.min(axis=1).max()/1000) - 1e-9)
        self.assertLessEqual(levels.max(), np.sqrt(400*ASPECT) + 1e-9)
        np.testing.assert_allclose(np.diff(levels), 0.5)

    def test_shapes_are_distinct_and_fill_the_area_budget(self):
        p = small_problem()
        found = shapes(p, 500, 400., 20)
        self.assertGreaterEqual(len(found), 2)
        widths = [w for w, _, _ in found]
        for k, (w, h, _) in enumerate(found):
            self.assertLessEqual(w*h, 400. + 1e-6)
            self.assertTrue(all(abs(w - v) > EXCLUDE*v for v in widths[:k]))
        rows = run_front(replace(p, carrier_um=(found[0][0]*1000, found[0][1]*1000)), 500, 30, 1, [],
                         dict(milp_s=10, workers=2, anneal_steps=10, chains=2))
        self.assertTrue(rows and all(np.isfinite(r['peak_c']) for r in rows))


if __name__ == '__main__':
    unittest.main()
