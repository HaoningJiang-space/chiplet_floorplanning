from dataclasses import dataclass
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from reach_split import link_classes, overshoot, verdict  # noqa: E402


@dataclass
class Named:
    names: tuple


def case(cc, cm, mem_over=0., ref_mem=0., comp_over=1.):
    def row(cost, over=None):
        r = dict(feasible=cost is not None, cost_k=cost)
        if over:
            r['overshoot_k'] = over
        return r
    return dict(reference_overshoot_k=dict(memory=ref_mem, compute=comp_over),
                classes={'compute-compute': row(cc),
                         'compute-memory': row(cm, dict(memory=mem_over, compute=comp_over))})


class ReachSplitTest(unittest.TestCase):
    def test_links_split_by_die_kind(self):
        problem = Named(('GPU_0', 'GPU_1', 'HBM_0', 'Analog_0', 'CPU2_0'))
        pairs = np.array([[0, 1], [0, 2], [2, 3], [1, 3], [2, 4]])
        split = link_classes(problem, pairs)
        self.assertEqual(split['compute-compute'].tolist(), [[0, 1]])
        self.assertEqual(split['compute-memory'].tolist(), [[0, 2], [2, 4]])

    def test_overshoot_uses_the_kind_limit(self):
        o = overshoot(Named(('GPU_0', 'HBM_0', 'IODie_0')), np.array([100., 97., 200.]))
        self.assertEqual(o, dict(compute=-5., memory=2.))

    def test_verdict_rules(self):
        dominant = [case(15., 2.), case(None, 1.), case(6., 0.1), case(3., 1.), case(1., 1.)]
        self.assertTrue(verdict(dominant)['compute_pairs_dominate'])
        self.assertFalse(verdict(dominant)['stop'])
        # not found counts as dominant only against a finite compute-memory cost
        self.assertEqual(verdict([case(None, None)])['counts']['compute_pairs_dominate'], 0)
        memory = [case(1., 3., mem_over=5., ref_mem=2.)]*2 + [case(1., 1.)]*3
        self.assertTrue(verdict(memory)['memory_limit_binds'])
        self.assertFalse(verdict(memory)['stop'])          # only 3 cases have both costs < 2 K
        self.assertTrue(verdict([case(1., 1.)]*4 + [case(9., 1.)])['stop'])
        self.assertFalse(verdict([case(1., 3., mem_over=3., ref_mem=2.)]*2)['memory_limit_binds'])


if __name__ == '__main__':
    unittest.main()
