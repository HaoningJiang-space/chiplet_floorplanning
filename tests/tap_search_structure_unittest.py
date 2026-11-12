import json
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from compare_tap_search import move_graph, search, score
from audit_tap_search_structure import component_members, pareto_bins


class StructureTest(unittest.TestCase):
    def test_atomic_cannot_cross_joint_only_edge(self):
        def row(x, rotation):
            return dict(placement=[dict(centre_x_um=x, centre_y_um=0, rotation_deg=rotation)])
        rows = [row(0, 0), row(1, 90), row(2, 90)]
        self.assertEqual(sorted(map(len, component_members(move_graph(rows, 'atomic')))), [1, 2])
        self.assertEqual(list(map(len, component_members(move_graph(rows, 'joint')))), [3])

    def test_numerical_ties_preserve_members_and_real_tradeoffs(self):
        rows = [dict(class_index=i, peak_c=t, centre_span_mm=s)
                for i, (t, s) in enumerate([(77., 31.), (77.-4e-11, 31.),
                                            (76., 40.), (78., 40.)])]
        bins = pareto_bins(rows)
        members = sorted(sorted(r['class_index'] for r in b['members']) for b in bins)
        self.assertEqual(members, [[0, 1], [2]])
        reversed_members = sorted(sorted(r['class_index'] for r in b['members'])
                                  for b in pareto_bins(list(reversed(rows))))
        self.assertEqual(members, reversed_members)

    def test_legacy_traces_unchanged_and_cost_identity(self):
        rows = json.loads((ROOT/'docs/evidence/tap-algorithm-oracle.json').read_text())['rows']
        old = json.loads((ROOT/'docs/evidence/tap-search-comparison.json').read_text())['runs']
        graph = move_graph(rows)
        for record in old:
            values = [score(r, rows[0], record['objective']) for r in rows]
            new = search(lambda i: values[i], len(rows), graph, record['budget'], record['seed'], record['method'])
            for key in ('queried_classes', 'best_class', 'best_score', 'proposals', 'restarts'):
                self.assertEqual(new[key], record[key])
            self.assertEqual(new['queries']+new['cache_hits'], new['proposals']+1)
