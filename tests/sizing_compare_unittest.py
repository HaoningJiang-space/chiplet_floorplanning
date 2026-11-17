from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_compare import SWEEP, compare_budget, front_points, reticle_decision, verdict  # noqa: E402


def rows(points):
    return [dict(length_m=l, thermal=t) for l, t in points]


def shape(size, points):
    return dict(width_mm=size[0], height_mm=size[1], rows=rows(points))


def record(factor, joint, base):
    """joint: [(size, points)]; base: (size, points)."""
    return dict(factor=factor, joint=[shape(s, p) for s, p in joint], baseline=shape(*base))


class SizingCompareTest(unittest.TestCase):
    def test_front_points_keep_the_pareto_front_only(self):
        pts = front_points(rows([(1., 100.), (2., 90.), (2.5, 95.), (3., 80.)]))
        self.assertEqual(pts, [(1., 100.), (2., 90.), (3., 80.)])
        self.assertEqual(front_points([dict(length_m=1., peak_c=90.)]), [(1., 90.)])   # exploratory sizing-v1 rows

    def test_budget_outcome(self):
        win = compare_budget(record(1.0, [((40., 40.), [(1., 90.), (2., 80.)])], ((40., 40.), [(1., 95.), (2., 85.)])))
        self.assertEqual(win['outcome'], 'ours')
        self.assertEqual(compare_budget(record(1.0, [((40., 40.), [])], ((40., 40.), [(1., 95.)])))['outcome'],
                         'unavailable')

    def test_verdict_counts_the_frozen_combinations(self):
        # Review of b50044e: one win and 59 unavailable gave "effective, 100%".
        self.assertEqual(verdict({0: 'ours', **{k: 'unavailable' for k in range(1, 60)}}, 60)[0], 'incomplete')
        self.assertEqual(verdict({k: 'unavailable' for k in range(60)}, 60)[0], 'incomplete')
        self.assertEqual(verdict({k: 'ours' for k in range(50)}, 60)[1]['missing'], 10)
        self.assertEqual(verdict({k: 'ours' if k < 24 else 'tie' for k in range(60)}, 60)[0], 'effective')
        self.assertEqual(verdict({k: 'atplace' if k < 15 else 'tie' for k in range(60)}, 60)[0], 'ineffective')

    def test_reticle_decision_separates_cost_sensitivity_from_thermal_drive(self):
        # Review of b50044e: two candidates with equal temperature and length but sizes 50x56 and 50x57 changed
        # option under the parameter sweep; that is cost sensitivity, not a thermally driven choice.
        same = [record(1.0, [((50., 57.), [(1., 80.)])], ((50., 56.), [(1., 80.)]))]
        out = reticle_decision(same)
        self.assertEqual(len(out['pairs']), len(SWEEP))
        self.assertEqual(out['thermally_driven_sets'], 0)
        # A cheap single-field interposer that is too hot vs a larger stitched one that meets the threshold.
        driven = [record(1.0, [((25., 32.), [(1.0, 95.)])], ((40., 40.), [(1.0, 85.)]))]
        out = reticle_decision(driven)
        self.assertEqual(out['t_cap'], 85.)
        self.assertGreater(out['thermally_driven_sets'], 0)
        first = out['pairs'][0]
        self.assertEqual((first['without_threshold']['option'], first['with_threshold']['option']), ('single', 'stitched'))
        # Wire budget: a candidate beyond 1.1x the baseline's shortest length is not in the pool.
        long = [record(1.0, [((25., 32.), [(5.0, 80.)])], ((40., 40.), [(1.0, 85.)]))]
        self.assertEqual(reticle_decision(long)['pairs'][0]['with_threshold']['option'], 'stitched')

    def test_only_unsupported_sizes_give_unsupported(self):
        huge = [record(1.0, [((60., 60.), [(1., 80.)])], ((60., 60.), [(1., 80.)]))]   # beyond 3.3 reticles
        self.assertEqual(reticle_decision(huge)['status'], 'unsupported')


if __name__ == '__main__':
    unittest.main()
