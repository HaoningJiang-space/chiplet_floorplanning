from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from compare_large_pool import Bank, choose


class IndependentPaths:
    """Four sites with distinct passive paths to a common ambient."""
    def __init__(self):
        self.transfer = np.diag([1.8,1.5,1.,1.1])
        self.active = np.arange(4)
        self.slots = [[i] for i in self.active]
        self.rows = {}

    def observe(self, node):
        self.rows[node] = self.transfer[node]

    def temperatures(self, watts):
        return self.transfer @ watts


class HotspotSwitchTest(unittest.TestCase):
    def test_new_hotspot_changes_second_choice_under_the_same_budget(self):
        pkg = IndependentPaths()
        watts = np.array([[4,3,2,1],[1,4,3,2],[1,4,2,3],[2,1,4,3]], dtype=float)
        assignments = np.array([[np.flatnonzero(row==w).item() for w in watts[0]] for row in watts])
        bank = Bank(assignments,watts,np.ones(4),np.ones(4),(1.,1.))
        initial = pkg.temperatures(watts[0])
        static = choose(bank,pkg,initial,'static',trace_switches=True)
        feedback = choose(bank,pkg,initial,'single',trace_switches=True)
        self.assertEqual([v['map_id'] for v in static['trace']], [1,2])
        self.assertEqual([v['map_id'] for v in feedback['trace']], [1,3])
        first, second = feedback['trace']
        self.assertGreater(first['excess_over_observers_k'], 4.)
        self.assertLess(first['after_response_bound_k'], first['after_check_bound_k'])
        self.assertAlmostEqual(static['best']['peak_c']-second['incumbent_c'],2.)
        self.assertAlmostEqual(second['after_response_bound_k'],0.,places=6)
        self.assertEqual(feedback['candidate_checks'],2)
        preset = choose(bank,pkg,initial,'static_three',trace_switches=True)
        self.assertEqual(preset['witnesses_by_stage'], [[0], [1], [2]])
        self.assertEqual(preset['responses'], 3)
        self.assertEqual(preset['candidates'][:2], feedback['candidates'][:2])
        self.assertEqual(preset['candidate_checks'], 2)
