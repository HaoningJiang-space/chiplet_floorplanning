import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from cosize_compare import certified, combos, compare, outcome, verdict  # noqa: E402


IDENTITY = dict(protocol_revision='cosize-v3.2', case_sha256='c', anchor_sha256='a', t_ref_c=100.0, l_ref_m=1.0,
                seed=2, fv_budget=1000, resources=dict(workers=16, wall_s=2400), code=dict(commit='x', dirty=None),
                milp_s=60)


def run(best=None, history=(), **identity):
    return dict(anchor=dict(ok=True, carrier_mm=[42.0, 42.0]), best=best and dict(width_mm=best[0], height_mm=best[1],
                                                                                  cost_usd=0.0), history=[
        dict(width_mm=w, height_mm=h, certified=c) for w, h, c in history],
        original=dict(width_mm=42.0, height_mm=42.0, total_usd=253.9), fv_solves=10, wall_s=1.0,
        **{**IDENTITY, **identity})


class CosizeCompareTest(unittest.TestCase):
    def test_outcome_rule(self):
        self.assertEqual(outcome(90., 100.), 'win')
        self.assertEqual(outcome(97., 100.), 'tie')
        self.assertEqual(outcome(106., 100.), 'loss')
        self.assertEqual(outcome(None, 100.), 'loss')
        self.assertEqual(outcome(100., None), 'win')
        self.assertEqual(outcome(None, None), 'unavailable')

    def test_certified_sizes_include_history_only_when_certified(self):
        r = run((30., 30.), [(30., 30., True), (25., 25., False), (35., 35., True)])
        self.assertEqual(certified(r), {(30., 30.), (35., 35.), (42., 42.)})   # plus the checked anchor's carrier

    def test_missing_runs_count_in_the_denominator(self):
        self.assertEqual(len(combos()), 18)                              # Case8 cool included by default
        self.assertEqual(len(combos(False)), 17)
        result, coverage = verdict({'a': 'win'}, 17)
        self.assertEqual(coverage['missing'], 16)
        self.assertEqual(result, 'incomplete')
        self.assertEqual(verdict({str(i): 'win' for i in range(7)}, 17)[0], 'incomplete')

    def test_compare_reads_files_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d/'case1-atp_wl-cosize.json').write_text(json.dumps(run((26., 30.), [(26., 30., True)])))
            (d/'case1-atp_wl-fixed_aspect.json').write_text(json.dumps(run((40., 40.), [(40., 40., True)])))
            report = compare(d, [(1, 'atp_wl')])
            row = report['cosize_vs_fixed_aspect']['rows']['case1-atp_wl']
            self.assertEqual(row['outcome'], 'win')
            self.assertEqual(report['cosize_vs_fixed_aspect']['verdict'], 'effective')
            self.assertIn('case1-atp_wl', report['cosize_savings_vs_original'])
            held = report['cosize_vs_fixed_aspect']['held_out']
            self.assertIn('case1-atp_wl', held['combinations'])           # not a development combination
            self.assertEqual(held['coverage']['wins'], 1)

    def test_runs_from_different_protocols_are_not_paired(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d/'case1-atp_wl-cosize.json').write_text(json.dumps(run((26., 30.))))
            for bad in (dict(protocol_revision='cosize-v2'), dict(seed=3), dict(fv_budget=100), dict(seed=None),
                        dict(resources=dict(workers=8, wall_s=2400)), dict(code=dict(commit='y', dirty=None)), dict(milp_s=30)):
                (d/'case1-atp_wl-fixed_aspect.json').write_text(json.dumps(run((40., 40.), **bad)))
                report = compare(d, [(1, 'atp_wl')])
                self.assertEqual(report['cosize_vs_fixed_aspect']['rows']['case1-atp_wl']['outcome'], 'unpaired')
                self.assertEqual(report['cosize_vs_fixed_aspect']['verdict'], 'incomplete')

    def test_a_failed_anchor_check_is_not_a_win(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d/'case1-atp_wl-cosize.json').write_text(json.dumps(run((26., 30.), [(26., 30., True)])))
            base = run(None)
            base['anchor'] = dict(ok=False)
            (d/'case1-atp_wl-fixed_aspect.json').write_text(json.dumps(base))
            report = compare(d, [(1, 'atp_wl')])
            self.assertEqual(report['cosize_vs_fixed_aspect']['rows']['case1-atp_wl']['outcome'], 'unpaired')
            self.assertEqual(report['cosize_vs_fixed_aspect']['verdict'], 'incomplete')

    def test_the_checked_anchor_stays_in_the_repriced_pool(self):
        r = run((26., 30.), [(26., 30., True)])
        r['anchor'] = dict(ok=True, carrier_mm=[42.0, 42.0])
        self.assertIn((42.0, 42.0), certified(r))
        r['anchor']['ok'] = False
        self.assertNotIn((42.0, 42.0), certified(r))


if __name__ == '__main__':
    unittest.main()
