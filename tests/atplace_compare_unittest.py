import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Problem, pin_manhattan_um, sample_legal  # noqa: E402
from atplace_compare import completeness, dominates, from_atplace, outcome, pick, to_atplace, verdict  # noqa: E402
import atplace_sweep  # noqa: E402
from atplace_sweep import LABELS, last_json, scored  # noqa: E402


class AtplaceCompareTest(unittest.TestCase):
    def test_layout_round_trip_keeps_centres_rotations_and_rotated_sizes(self):
        problem = Problem.from_imported(synthetic_case(random.Random(29), chips=4, nets=30))
        layout = sample_legal(problem, 1000, np.random.default_rng(8))
        data = to_atplace(problem, layout, 'CaseX')
        back = from_atplace(problem, data)
        np.testing.assert_allclose(back.centre_um, layout.centre_um)
        np.testing.assert_array_equal(back.rotation_deg % 360, layout.rotation_deg % 360)
        self.assertEqual(pin_manhattan_um(problem, back).sum(), pin_manhattan_um(problem, layout).sum())
        k = int(np.flatnonzero(layout.rotation_deg % 180 != 0)[0]) if (layout.rotation_deg % 180 != 0).any() else 0
        expect = problem.size_um[k][::-1] if layout.rotation_deg[k] % 180 else problem.size_um[k]
        self.assertEqual([data['chiplets'][k]['width'], data['chiplets'][k]['height']], list(expect))

    def test_margin_dominance_and_outcomes(self):
        self.assertTrue(dominates((10, 99), (10, 100)))
        self.assertFalse(dominates((10, 99.5), (10, 100)))
        self.assertTrue(dominates((9, 100), (10, 100)))
        self.assertFalse(dominates((9.5, 100), (10, 100)))
        ours = [(10, 90), (20, 85)]
        win = outcome(ours, [(12, 95), (25, 88)])
        self.assertEqual((win['d_ours'], win['d_atp'], win['outcome']), (1.0, 0.0, 'ours'))
        self.assertAlmostEqual(win['points'][0]['delta_t_k'], 5)
        lose = outcome(ours, [(5, 80)])
        self.assertEqual(lose['outcome'], 'atplace')
        self.assertIsNone(lose['points'][0]['delta_t_k'])

    def test_verdict_rules(self):
        c = lambda r: dict(outcome=r)
        self.assertEqual(verdict({'fv': [c('ours')]*7 + [c('tie')]*3, 'atsim': [c('ours')]*7 + [c('tie')]*3})[0], 'advantage')
        self.assertEqual(verdict({'fv': [c('ours')]*10, 'atsim': [c('atplace')]*5 + [c('ours')]*5})[0], 'no_advantage')
        self.assertEqual(verdict({'fv': [c('ours')]*3 + [c('tie')]*7, 'atsim': [c('ours')]*2 + [c('tie')]*8})[0], 'no_advantage')
        self.assertEqual(verdict({'fv': [c('ours')]*8 + [c('tie')]*2, 'atsim': [c('ours')]*5 + [c('tie')]*5})[0], 'partial')

    def test_pick_and_summary_parsing(self):
        self.assertEqual(pick(np.array([3., 1., 2., 5., 4.]), 3), [0, 1, 3])   # shortest, median, longest
        self.assertEqual(last_json('progress {not json}\n{\n "a": 1\n}\nnoise\n{"b": {"c": 2}}\n'), {'b': {'c': 2}})

    def test_failed_points_make_a_case_incomplete_instead_of_shrinking_the_denominator(self):
        rows = [dict(label='wl', legal=True)]
        info = completeness({'train_failed': 'sampler'}, rows)
        self.assertEqual((info['scored'], info['complete'], info['missing']), (1, False, []))
        self.assertEqual(info['failed'], sorted(LABELS[1:]))
        info = completeness({'thermal_x10': dict(failed='x')}, [dict(label=l, legal=l != 'wl') for l in LABELS
                                                                if l != 'thermal_x10'])
        self.assertEqual((info['failed'], info['illegal'], info['complete']), (['thermal_x10'], ['wl'], False))
        self.assertTrue(completeness({}, [dict(label=l, legal=True) for l in LABELS])['complete'])

    def test_verdict_is_incomplete_for_missing_points_or_a_case_subset(self):
        c = lambda r: dict(outcome=r)
        wins = {'fv': [c('ours')]*10, 'atsim': [c('ours')]*10}
        self.assertEqual(verdict(wins, [True]*7 + [False]*3), ('incomplete', {'fv': 7, 'atsim': 7}, {'fv': 0, 'atsim': 0}))
        self.assertEqual(verdict({'fv': [c('ours')], 'atsim': [c('ours')]}, [True])[0], 'incomplete')
        self.assertEqual(verdict({'fv': [c('tie')], 'atsim': [c('tie')]}, [True])[0], 'incomplete')   # not no_advantage
        self.assertEqual(verdict(wins, [True]*10)[0], 'advantage')

    def test_atsim_score_is_reused_only_when_newer_than_its_layout(self):
        with tempfile.TemporaryDirectory() as d:
            layout, score = Path(d)/'layout.json', Path(d)/'atsim.json'
            layout.write_text('{}')
            self.assertFalse(scored(score, layout))
            score.write_text('{}')
            os.utime(layout, (1e9, 1e9)); os.utime(score, (2e9, 2e9))
            self.assertTrue(scored(score, layout))
            os.utime(layout, (3e9, 3e9))    # a rerun rewrote the layout after it was scored
            self.assertFalse(scored(score, layout))

    def test_failed_rerun_removes_the_previous_runs_layouts(self):
        with tempfile.TemporaryDirectory() as d:
            out, new = Path(d)/'out', Path(d)/'new_layout.json'
            new.write_text('{}')
            for label in LABELS:
                (out/'CaseX'/label).mkdir(parents=True)
                (out/'CaseX'/label/'layout.json').write_text('{"old": 1}')

            def run(cmd, log):
                if 'run_thermal_training.py' in cmd:
                    raise RuntimeError('sampler')
                if 'run_placement_opt.py' in cmd:
                    return dict(layout_json=str(new)), 1.0
                return dict(tmax_c=80.0), 1.0
            with mock.patch.object(atplace_sweep, 'run', run), mock.patch.object(atplace_sweep, 'params', lambda *a: {}):
                timing = atplace_sweep.sweep('CaseX', out, 1, None)
            self.assertIn('train_failed', timing)
            self.assertEqual(sorted(p.parent.name for p in (out/'CaseX').glob('*/layout.json')), ['wl'])
            self.assertEqual(json.loads((out/'CaseX'/'wl'/'layout.json').read_text()), {})


if __name__ == '__main__':
    unittest.main()
