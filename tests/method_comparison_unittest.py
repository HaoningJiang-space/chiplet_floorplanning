import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from scipy import sparse

from chiplet_floorplanning.package import require_heat_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from run_method_comparison import checked_records, in_seed_order, same_problem


class ComparisonProtocolTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name, text in (('case.json', '{}'), ('ref.json', '{"front": []}')):
            (self.dir/name).write_text(text)
        sha = lambda name: hashlib.sha256((self.dir/name).read_bytes()).hexdigest()
        self.plan = dict(case_path=str(self.dir/'case.json'), case_sha256=sha('case.json'),
                         reference_summary=str(self.dir/'ref.json'), reference_sha256=sha('ref.json'),
                         methods=['random'], seeds=[1, 2], fv_solves=10)
        self.plan_path = self.dir/'plan.json'
        self.plan_path.write_text(json.dumps(self.plan))
        self.out = self.dir/'out'
        self.out.mkdir()
        for seed in (1, 2):
            self.record(seed)

    def record(self, seed, **change):
        row = dict(method='random', seed=seed, fv_solves=10,
                   plan_sha256=hashlib.sha256(self.plan_path.read_bytes()).hexdigest())
        row.update(change)
        (self.out/f'random-seed{seed}.json').write_text(json.dumps(row))
        (self.out/f'random-seed{seed}.npz').write_bytes(b'')

    def test_complete_records_pass(self):
        self.assertEqual(len(checked_records(self.plan_path, self.plan, self.out)), 2)

    def test_changed_reference_is_refused(self):
        (self.dir/'ref.json').write_text('{"front": [{"peak_c": 0}]}')
        with self.assertRaises(SystemExit):
            checked_records(self.plan_path, self.plan, self.out)

    def test_missing_seed_is_refused(self):
        (self.out/'random-seed2.json').unlink()
        with self.assertRaises(SystemExit):
            checked_records(self.plan_path, self.plan, self.out)

    def test_other_plan_or_overspent_budget_is_refused(self):
        for change in (dict(plan_sha256='0'*64), dict(fv_solves=11)):
            with self.subTest(change=change):
                self.record(2, **change)
                with self.assertRaises(SystemExit):
                    checked_records(self.plan_path, self.plan, self.out)
                self.record(2)
    def test_seed_labels_follow_the_plan_not_file_order(self):
        records = [dict(method='random', seed=10, value='b'), dict(method='random', seed=2, value='a')]
        self.assertEqual([r['value'] for r in in_seed_order(records, 'random', [2, 10])], ['a', 'b'])

    def test_reference_must_describe_the_same_problem(self):
        case = self.dir/'case1.json'
        case.write_text(json.dumps(dict(name='Case1')))
        good = dict(status='completed', case='Case1', gap_um=0.0, fv_resolution=64,
                    case_sha256=hashlib.sha256(case.read_bytes()).hexdigest())
        same_problem(good, case, 0.0, 64)
        for change in (dict(case='Case2'), dict(case_sha256='0'*64), dict(gap_um=1000.0),
                       dict(fv_resolution=32), dict(status='failed_initialization')):
            with self.subTest(change=change), self.assertRaises(SystemExit):
                same_problem({**good, **change}, case, 0.0, 64)
        unrecorded = {k: v for k, v in good.items() if k != 'case_sha256'}
        with self.assertRaises(SystemExit):
            same_problem(unrecorded, case, 0.0, 64)


class HeatPathTest(unittest.TestCase):
    def test_isolated_conduction_component_is_rejected(self):
        # Nodes 0-1 reach the sink; nodes 2-3 form an adiabatic island with G z = 0.
        g = sparse.csr_matrix(np.array([[2., -1, 0, 0], [-1, 1, 0, 0], [0, 0, 1, -1], [0, 0, -1, 1]]))
        with self.assertRaises(ValueError):
            require_heat_path(g, np.array([1., 0, 0, 0]))
        require_heat_path(g, np.array([1., 0, 1, 0]))


if __name__ == '__main__':
    unittest.main()
