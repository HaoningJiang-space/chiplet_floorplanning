from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_compare import SWEEP, compare_budget, front_points, reticle_decision, verdict  # noqa: E402


def rows(points):
    return [dict(length_m=l, peak_c=t) for l, t in points]


def record(factor, joint, base, size=(40., 40.)):
    return dict(factor=factor, joint=[dict(width_mm=size[0], height_mm=size[1], rows=rows(joint))],
                baseline=dict(width_mm=size[0], height_mm=size[1], rows=rows(base)))


class SizingCompareTest(unittest.TestCase):
    def test_front_points_keep_the_pareto_front_only(self):
        pts = front_points(rows([(1., 100.), (2., 90.), (2.5, 95.), (3., 80.)]))
        self.assertEqual(pts, [(1., 100.), (2., 90.), (3., 80.)])

    def test_budget_outcome_and_verdict(self):
        win = compare_budget(record(1.0, [(1., 90.), (2., 80.)], [(1., 95.), (2., 85.)]))
        self.assertEqual(win['outcome'], 'ours')
        self.assertEqual(compare_budget(record(1.0, [], [(1., 95.)]))['outcome'], 'unavailable')
        self.assertEqual(verdict(['ours']*4 + ['tie']*6)[0], 'effective')
        self.assertEqual(verdict(['atplace']*3 + ['tie']*7)[0], 'ineffective')
        self.assertEqual(verdict(['ours']*3 + ['tie']*7)[0], 'partial')

    def test_reticle_decision_uses_the_original_size_cap_and_all_parameter_sets(self):
        records = [record(1.0, [(1., 90.)], [(1., 95.)], (40., 40.)), record(0.85, [(1., 94.)], [(1., 99.)], (25., 32.))]
        out = reticle_decision(records)
        self.assertEqual(out['t_cap_c'], 95.)
        self.assertEqual(len(out['choices']), len(SWEEP))
        # The single-field 25 x 32 mm layout meets the cap (94 <= 95) and is the cheapest under every parameter set.
        self.assertEqual(out['distinct'], ["('single', 1)"])
        self.assertFalse(out['changes'])


if __name__ == '__main__':
    unittest.main()
