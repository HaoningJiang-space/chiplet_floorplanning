import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from run_method_comparison import checked_records


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

if __name__ == '__main__':
    unittest.main()
