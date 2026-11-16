import unittest

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Problem, is_legal
from chiplet_floorplanning.placement.lp import legalize_relations, milp_relations
from chiplet_floorplanning.placement.methods import Run, thermal_space
from chiplet_floorplanning.placement.thermal_milp import ThermalTable


def small_problem():
    # A hot die, a warm rectangular die and a cool die with a few nets, on a 30 mm carrier.
    pins = np.array([[0, 1]]*6 + [[1, 2]]*4 + [[0, 2]]*2)
    return Problem('small', ('hot', 'warm', 'cool'), np.array([[6000., 6000.], [4000., 8000.], [6000., 6000.]]),
                   np.array([40., 20., 10.]), (30000., 30000.), pins, np.zeros((len(pins), 2, 2)))


class ThermalMilpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.problem = small_problem()
        cls.table = ThermalTable(cls.problem, 500, grid=3, resolution=16)
        cls.initial_solves = cls.table.solves
        cls.table.build()

    def test_table_types_cells_and_self_heating(self):
        t = self.table
        self.assertEqual(sorted(t.types), [(4000., 8000.), (6000., 6000.), (8000., 4000.)])
        self.assertEqual((self.initial_solves, t.solves), (sum(len(t.cells[o]) for o in t.types), 0))
        for o in t.types:
            k = t.K[o][o]
            self.assertTrue((k >= 0).all())
            self.assertTrue(all(k[c, c] >= k[c].max() - 1e-9 for c in range(len(k))))   # a die heats itself most

    def test_cap_bounds_the_kernel_peak_and_min_peak_is_coolest(self):
        p, t = self.problem, self.table
        shortest = milp_relations(p, 500, 20)
        coolest = milp_relations(p, 500, 20, thermal=(t, None))
        self.assertLessEqual(t.kernel_peak_c(coolest), t.kernel_peak_c(shortest) + 1e-9)
        cap = (t.kernel_peak_c(coolest) + t.kernel_peak_c(shortest))/2
        capped = milp_relations(p, 500, 20, thermal=(t, cap))
        self.assertLessEqual(t.kernel_peak_c(capped), cap + 1e-6)
        legal = legalize_relations(p, capped, 500)
        self.assertTrue(legal is not None and is_legal(p, legal, 500))
        self.assertIsNone(milp_relations(p, 500, 20, thermal=(t, t.kernel_peak_c(coolest) - 1.0)))

    def test_thermal_space_charges_kernel_solves_and_keeps_notes(self):
        p = self.problem
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 80)
            thermal_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, grid=3, levels=2,
                          cap_milp_s=10, batch=4)
            notes = run.notes['thermal_milp']
            self.assertEqual(notes['kernel_solves'], self.initial_solves)
            self.assertGreaterEqual(evaluator.solves, notes['kernel_solves'])
            self.assertEqual(len(notes['results']), 3)
            self.assertTrue(all(r['fv_peak_c'] is not None for r in notes['results'] if r['legal']))
            self.assertLessEqual(evaluator.solves, 80)
        with Evaluator(p, 500, resolution=16) as evaluator:     # too small a budget: the thermal part is skipped
            run = Run(evaluator, 10)
            thermal_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, grid=3, batch=4)
            self.assertIn('skipped', run.notes['thermal_milp'])
            self.assertLessEqual(evaluator.solves, 10)
            self.assertTrue(run.layouts and all(is_legal(p, l, 500) for l in run.layouts))

    def test_adaptive_refinement_splits_around_the_solution_and_keeps_the_cap(self):
        p = self.problem
        t = ThermalTable(p, 500, grid=3, resolution=16).build()
        coarse = milp_relations(p, 500, 20, thermal=(t, None))
        before = {o: len(c) for o, c in t.cells.items()}
        dry = t.refine(coarse, apply=False)
        self.assertEqual({o: len(c) for o, c in t.cells.items()}, before)     # a budget check changes nothing
        self.assertIsNotNone(t.K)
        pending = t.refine(coarse)
        self.assertEqual(pending, dry)
        self.assertGreater(pending, 0)
        self.assertTrue(any(len(t.cells[o]) > before[o] for o in t.types))
        for o in t.types:      # the cells still tile the feasible centre range exactly
            c = t.cells[o]
            w, h = o
            area = ((c[:, 1] - c[:, 0])*(c[:, 3] - c[:, 2])).sum()
            self.assertAlmostEqual(area, (30000 - w)*(30000 - h), delta=1e-3)
        t.build()
        self.assertEqual(t.solves, 0)
        fine = milp_relations(p, 500, 20, thermal=(t, None))
        cap = t.kernel_peak_c(fine) + 1.0
        capped = milp_relations(p, 500, 20, thermal=(t, cap))
        self.assertLessEqual(t.kernel_peak_c(capped), cap + 1e-6)
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 200)
            thermal_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, grid=3, levels=1,
                          cap_milp_s=10, refine=1, batch=4)
            notes = run.notes['thermal_milp']
            self.assertGreater(notes['kernel_solves'], self.initial_solves)
            self.assertLessEqual(evaluator.solves, 200)
        with Evaluator(p, 500, resolution=16) as evaluator:     # the budget allows the table but no refinement
            run = Run(evaluator, self.initial_solves + 8)
            thermal_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, grid=3, levels=1,
                          cap_milp_s=10, refine=2, batch=4)
            self.assertEqual(run.notes['thermal_milp']['kernel_solves'], self.initial_solves)
            self.assertTrue(run.notes['thermal_milp']['results'])

    def test_calibrated_caps_follow_fv_targets(self):
        p = self.problem
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 200)
            thermal_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, grid=3, levels=2,
                          cap_milp_s=10, calibrate=1, batch=4)
            rows = run.notes['thermal_milp']['results']
            targets = [r for r in rows if r['target_c'] is not None]
            self.assertEqual(len(targets), 2*2)                    # two targets, one correction each
            self.assertEqual(len({r['target_c'] for r in targets}), 2)
            for first, second in zip(targets[::2], targets[1::2]):
                if first['fv_peak_c'] is not None:             # the second cap moves by the first FV miss
                    self.assertAlmostEqual(second['cap_c'], first['cap_c'] + first['target_c'] - first['fv_peak_c'])
            self.assertLessEqual(evaluator.solves, 200)


if __name__ == '__main__':
    unittest.main()
