from dataclasses import replace
from pathlib import Path
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from placement_core_unittest import synthetic_case  # noqa: E402
from chiplet_floorplanning.placement import (Evaluator, Layout, Problem, is_legal, pin_manhattan_um,  # noqa: E402
                                             sample_legal)
from chiplet_floorplanning.placement.lp import hotspot_move, legalize_relations, slp_chain  # noqa: E402
from chiplet_floorplanning.placement.methods import METHODS, Run  # noqa: E402
from chiplet_floorplanning.placement.thermal import die_peak_sensitivity  # noqa: E402


class ThermalSlpTest(unittest.TestCase):
    def setUp(self):
        # Hot dies 2-4.5 mm apart, so every +-0.5 mm move is legal and mutual heating is well above mesh noise.
        problem = Problem.from_imported(synthetic_case(random.Random(41), chips=4, nets=60))
        self.problem = replace(problem, power_w=np.array([40., 30., 60., 50.]))
        self.layout = Layout(np.array([[10000., 10000.], [17000., 10000.], [10000., 18000.], [18000., 18000.]]),
                             np.zeros(4, int))

    def exact(self, layout, resolution=24):
        with Evaluator(self.problem, 1000, resolution=resolution) as evaluator:
            return evaluator.die_peaks_c([layout])[0]

    def test_sensitivity_peaks_are_exact_and_gradients_follow_finite_differences(self):
        peaks, grad = die_peak_sensitivity(self.problem, self.layout, 1000, 48)
        np.testing.assert_allclose(peaks, self.exact(self.layout, 48), atol=1e-8)
        predicted, measured = [], []
        for j in range(self.problem.count):
            for axis in (0, 1):
                moved = []
                for step in (500., -500.):
                    centre = self.layout.centre_um.copy()
                    centre[j, axis] += step
                    moved.append(Layout(centre, self.layout.rotation_deg.copy()))
                if all(is_legal(self.problem, m, 1000) for m in moved):
                    measured.append((self.exact(moved[0], 48) - self.exact(moved[1], 48))/1.0)
                    predicted.append(grad[:, j, axis])
        p, m = np.ravel(predicted), np.ravel(measured)
        self.assertEqual(len(p), 4*8)
        self.assertGreater(np.corrcoef(p, m)[0, 1], 0.7)   # 0.78 here; 0.82-0.89 on ATPlace Case1/3/4

    def test_chain_reports_exact_legal_layouts_and_never_lengthens_under_the_cap(self):
        start_peak = self.exact(self.layout).max()
        cap = start_peak + 2.0
        chain = slp_chain((self.problem, self.layout, 1000, 24, cap, 4))
        self.assertIs(chain[0][0], self.layout)
        for layout, die_peaks in chain:
            self.assertTrue(is_legal(self.problem, layout, 1000))
            np.testing.assert_allclose(die_peaks, self.exact(layout), atol=1e-8)
        under = [pin_manhattan_um(self.problem, l).sum() for l, d in chain if d.max() <= cap]
        self.assertLessEqual(min(under), pin_manhattan_um(self.problem, self.layout).sum())

    def test_topology_slp_respects_the_budget_and_records_exact_peaks(self):
        rng = np.random.default_rng(6)
        start = [sample_legal(self.problem, 1000, rng) for _ in range(4)]
        with Evaluator(self.problem, 1000, resolution=24) as evaluator:
            run = Run(evaluator, 40)
            METHODS['topology_slp'](run, start, np.random.default_rng(3), batch=4, caps=2, steps=3)
            self.assertLessEqual(evaluator.solves, 40)
        _, peak, _ = run.arrays()
        for k in range(0, len(run.layouts), max(1, len(run.layouts)//5)):
            self.assertAlmostEqual(peak[k], self.exact(run.layouts[k]).max(), places=8)

    def test_topology_slp_never_computes_more_solves_than_its_budget(self):
        # Count every FV solve and every SLP factorisation actually performed, independent of the bookkeeping.
        import chiplet_floorplanning.placement.evaluate as evaluate
        import chiplet_floorplanning.placement.thermal as thermal
        calls = []
        peaks, sensitivity = evaluate._peaks, thermal.peak_sensitivity
        evaluate._peaks = lambda job: calls.append(1) or peaks(job)
        thermal.peak_sensitivity = lambda *a, **k: calls.append(1) or sensitivity(*a, **k)
        try:
            rng = np.random.default_rng(6)
            start = [sample_legal(self.problem, 1000, rng) for _ in range(4)]
            for budget in (12, 20, 40):
                calls.clear()
                with Evaluator(self.problem, 1000, resolution=24) as evaluator:
                    run = Run(evaluator, budget)
                    METHODS['topology_slp'](run, start, np.random.default_rng(3), batch=4, caps=3, steps=4)
                    self.assertLessEqual(len(calls), budget)
                    self.assertEqual(evaluator.solves, len(calls))
        finally:
            evaluate._peaks, thermal.peak_sensitivity = peaks, sensitivity

    def test_length_mode_keeps_the_budget_and_never_heats(self):
        budget = pin_manhattan_um(self.problem, self.layout).sum()/1e6
        chain = slp_chain((self.problem, self.layout, 1000, 24, budget, 4, 'length'))
        start_peak = chain[0][1].max()
        within = [d.max() for l, d in chain if pin_manhattan_um(self.problem, l).sum()/1e6 <= budget + 1e-9]
        self.assertLessEqual(min(within), start_peak)
        for layout, die_peaks in chain:
            self.assertTrue(is_legal(self.problem, layout, 1000))
            np.testing.assert_allclose(die_peaks, self.exact(layout), atol=1e-8)

    def test_hotspot_move_and_relation_legalisation_return_legal_layouts(self):
        peaks = self.exact(self.layout)
        rng = np.random.default_rng(4)
        for _ in range(20):
            moved = hotspot_move(self.problem, self.layout, peaks, rng, 1000)
            self.assertTrue(moved is None or is_legal(self.problem, moved, 1000))
        overlapping = Layout(self.layout.centre_um*np.array([[0.9, 1.0]]), self.layout.rotation_deg.copy())
        fixed = legalize_relations(self.problem, overlapping, 1000)
        self.assertTrue(fixed is not None and is_legal(self.problem, fixed, 1000))

    def test_both_targets_with_hotspot_moves_stay_within_budget(self):
        rng = np.random.default_rng(6)
        start = [sample_legal(self.problem, 1000, rng) for _ in range(4)]
        with Evaluator(self.problem, 1000, resolution=24) as evaluator:
            run = Run(evaluator, 30)
            METHODS['topology_slp'](run, start, np.random.default_rng(3), batch=4, caps=2, steps=3,
                                    targets='both', hotspot=0.5)
            self.assertLessEqual(evaluator.solves, 30)


if __name__ == '__main__':
    unittest.main()
