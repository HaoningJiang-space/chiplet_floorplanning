"""Regression tests for the 0ef1f47 review (docs/evidence/code-review-0ef1f47.json)."""
from dataclasses import replace
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem, sample_legal  # noqa: E402
from chiplet_floorplanning.placement.evaluate import thermal_key  # noqa: E402
import chiplet_floorplanning.placement.methods as methods  # noqa: E402
from chiplet_floorplanning.placement.lp import hotspot_move  # noqa: E402
from run_reference_front import parse_options  # noqa: E402


class SlpDispatchTest(unittest.TestCase):
    def setUp(self):
        problem = Problem.from_imported(synthetic_case(random.Random(41), chips=4, nets=60))
        self.problem = replace(problem, power_w=np.array([40., 30., 60., 50.]))
        rng = np.random.default_rng(6)
        self.start = [sample_legal(self.problem, 1000, rng) for _ in range(4)]

    def test_multi_mode_evaluators_are_rejected(self):
        rows, limits = np.array([self.problem.power_w]), np.full(4, 100.)
        with Evaluator(self.problem, 1000, resolution=24, modes=(rows, limits)) as evaluator:
            with self.assertRaises(ValueError):
                methods.topology_slp(methods.Run(evaluator, 20), self.start, np.random.default_rng(3), batch=4)

    def test_trimmed_jobs_stay_eligible_so_length_targets_run(self):
        # Chains that stop at their start (one factorisation, nothing new) leave budget and the archive
        # unchanged, so the next round proposes the same goals: the chains trimmed by the budget in the first
        # round (the length ones, listed after the peak ones) must run then instead of being marked tried.
        from chiplet_floorplanning.placement.thermal import die_peak_sensitivity
        modes, real = [], methods.slp_chain

        def stop_at_start(job):
            modes.append(job[6])
            return [(job[1], die_peak_sensitivity(job[0], job[1], job[2], job[3])[0])]
        methods.slp_chain = stop_at_start
        try:
            with Evaluator(self.problem, 1000, resolution=24) as evaluator:
                run = methods.Run(evaluator, 30, stall_rounds=50)
                methods.topology_slp(run, self.start, np.random.default_rng(3), batch=4, caps=6, steps=1,
                                     lp_share=0.5, targets='both', explore=0.0)
        finally:
            methods.slp_chain = real
        self.assertIn('length', modes)

    def test_job_identity_includes_pin_orientation(self):
        layout = self.start[0]
        turned = Layout(layout.centre_um.copy(), (layout.rotation_deg + np.array([180, 0, 0, 0])) % 360)
        self.assertEqual(thermal_key(self.problem, layout), thermal_key(self.problem, turned))
        self.assertNotEqual(methods.slp_job_key(self.problem, layout, 100., 'peak'),
                            methods.slp_job_key(self.problem, turned, 100., 'peak'))

    def test_hotspot_move_survives_zero_power_neighbours(self):
        problem = replace(self.problem, power_w=np.array([40., 0., 0., 0.]))
        rng = np.random.default_rng(0)
        for _ in range(50):
            hotspot_move(problem, self.start[0], np.array([90., 50., 50., 50.]), rng, 1000)


class ReferenceFrontCliTest(unittest.TestCase):
    def test_options_keep_their_types(self):
        self.assertEqual(parse_options(['caps=2', 'milp_s=0.5', 'targets=length']),
                         dict(caps=2, milp_s=0.5, targets='length'))
        self.assertIs(type(parse_options(['caps=2'])['caps']), int)

    def test_length_caps_reach_epsilon_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)/'case.json'
            case.write_text(json.dumps(import_case('fixture', BLOCKS, POWER, NETS)))
            out = Path(tmp)/'out'
            subprocess.run([sys.executable, str(ROOT/'tools'/'run_reference_front.py'), '--case', str(case),
                            '--method', 'epsilon', '--fv-solves', '12', '--length-caps-m', '1e9',
                            '--random-starts', '2', '--descent-starts', '2', '--resolution', '16',
                            '--workers', '1', '--gap-um', '0', '--output', str(out)],
                           check=True, capture_output=True, env={'PYTHONPATH': str(ROOT/'src')})
            summary = json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['distinct_fv_solves'], 12)


if __name__ == '__main__':
    unittest.main()
