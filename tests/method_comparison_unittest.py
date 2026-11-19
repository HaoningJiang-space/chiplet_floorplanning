import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy import sparse

from chiplet_floorplanning.package import require_heat_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from run_method_comparison import checked_records, execute, in_seed_order, report, same_problem


class ComparisonProtocolTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name, text in (('case.json', '{}'), ('ref.json', '{"front": []}')):
            (self.dir/name).write_text(text)
        sha = lambda name: hashlib.sha256((self.dir/name).read_bytes()).hexdigest()
        self.plan = dict(case_path=str(self.dir/'case.json'), case_sha256=sha('case.json'),
                         reference_summary=str(self.dir/'ref.json'), reference_sha256=sha('ref.json'),
                         methods=['random'], seeds=[1, 2], fv_solves=10,
                         code=dict(commit='revision-a', dirty=False))
        self.plan_path = self.dir/'plan.json'
        self.plan_path.write_text(json.dumps(self.plan))
        self.out = self.dir/'out'
        self.out.mkdir()
        for seed in (1, 2):
            self.record(seed)

    def record(self, seed, **change):
        row = dict(method='random', seed=seed, fv_solves=10, code_commit='revision-a', code_dirty=False,
                   plan_sha256=hashlib.sha256(self.plan_path.read_bytes()).hexdigest())
        row.update(change)
        (self.out/f'random-seed{seed}.json').write_text(json.dumps(row))
        (self.out/f'random-seed{seed}.npz').write_bytes(b'')

    def test_complete_records_pass(self):
        self.assertEqual(len(checked_records(self.plan_path, self.plan, self.out)), 2)

    def test_legacy_reports_require_clean_matching_revisions(self):
        for change in (dict(code_commit='revision-b'), dict(code_dirty=True), dict(code_dirty=None)):
            self.record(2, **change)
            with self.subTest(change=change), self.assertRaises(SystemExit):
                checked_records(self.plan_path, self.plan, self.out)

    def test_pinned_code_allows_docs_commits_and_rejects_changed_implementations(self):
        self.plan['code']['implementation_sha256'] = 'frozen-digest'
        self.plan_path.write_text(json.dumps(self.plan))
        for seed in (1, 2):
            self.record(seed, code_commit='docs-commit', implementation_sha256='frozen-digest')
        self.assertEqual(len(checked_records(self.plan_path, self.plan, self.out)), 2)
        for change in (dict(implementation_sha256='other'), dict(code_dirty=True), dict(code_dirty=None)):
            self.record(2, **(dict(implementation_sha256='frozen-digest') | change))
            with self.subTest(change=change), self.assertRaises(SystemExit):
                checked_records(self.plan_path, self.plan, self.out)
        with patch('run_method_comparison.implementation', return_value=dict(
                commit='revision-a', dirty=False, implementation_sha256='other')):
            with self.assertRaisesRegex(SystemExit, 'implementation'):
                execute(SimpleNamespace(plan=self.plan_path, output=self.dir/'new'))
            self.assertFalse((self.dir/'new').exists())

    def test_archive_requires_explicit_status_and_matching_content(self):
        self.plan['code']['implementation_sha256'] = 'frozen-digest'
        self.plan_path.write_text(json.dumps(self.plan))
        for seed in (1, 2):
            self.record(seed, code_source_kind='archive', code_dirty=None, implementation_sha256='frozen-digest')
        self.assertEqual(len(checked_records(self.plan_path, self.plan, self.out)), 2)
        path = self.out/'random-seed2.json'
        row = json.loads(path.read_text())
        del row['code_dirty']
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(SystemExit, 'source status'):
            checked_records(self.plan_path, self.plan, self.out)

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
    def test_zero_best_length_keeps_absolute_gap_only(self):
        # Review of bbff17f: coincident boundary pins give a 0 m best length and the
        # relative gap divided by it.
        (self.dir/'ref.json').write_text(json.dumps(dict(front=[dict(length_m=0., peak_c=50.)])))
        self.plan.update(reference_sha256=hashlib.sha256((self.dir/'ref.json').read_bytes()).hexdigest(),
                         length_caps_m=[1.], peak_caps_c=[60.])
        self.plan_path.write_text(json.dumps(self.plan))
        point = dict(coolest_within_length_cap={'1.0': dict(peak_c=51.)},
                     shortest_within_peak_cap={'60.0': dict(length_m=.5)})
        for seed in (1, 2):
            self.record(seed, stop_reason='budget', metrics={'0.25': point, '0.5': point, '1.0': point})
            np.savez(self.out/f'random-seed{seed}.npz', length_m=np.array([.5]), peak_c=np.array([51.]))
        report(type('Args', (), dict(plan=self.plan_path, output=self.out))())
        final = json.loads((self.out/'report.json').read_text())['methods']['random']['1.0']
        self.assertEqual(final['length_gap_m'], {'60.0': [.5, .5]})
        self.assertEqual(final['length_gap_fraction'], {})
        self.assertEqual(final['peak_gap_k'], {'1.0': [1., 1.]})

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
