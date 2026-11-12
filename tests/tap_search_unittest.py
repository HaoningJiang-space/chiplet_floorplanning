from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from compare_tap_search import search,components


class QueryBudgetTest(unittest.TestCase):
    def test_disconnected_graph_restarts_without_exceeding_query_budget(self):
        graph=[[1],[0],[3],[2],[]]
        self.assertEqual(components(graph),[2,2,1])
        for method in ('random','descent','annealing'):
            calls=[]
            def query(i):calls.append(i);return [5.,4.,3.,2.,1.][i]
            result=search(query,5,graph,5,7,method)
            self.assertEqual(result['best_class'],4)
            self.assertEqual(len(calls),5)
            self.assertEqual(len(set(calls)),5)
            self.assertEqual(result['queries'],5)

    def test_policies_cannot_query_unbudgeted_oracle_values(self):
        for method in ('random','descent','annealing'):
            calls=[]
            def query(i):
                calls.append(i)
                if len(calls)>3:raise AssertionError('Oracle information leak')
                return float(i)
            result=search(query,6,[[j for j in range(6) if j!=i] for i in range(6)],3,1,method)
            self.assertEqual(result['queried_classes'],calls)
            self.assertEqual(result['best_score'],0)


if __name__=='__main__':unittest.main()
