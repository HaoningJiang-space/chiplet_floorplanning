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
        cls.table = ThermalTable(cls.problem, 500, grid=3, resolution=16).build()

    def test_table_types_cells_and_self_heating(self):
        t = self.table
        self.assertEqual(sorted(t.types), [(4000., 8000.), (6000., 6000.), (8000., 4000.)])
        self.assertEqual(t.solves, sum(t.allowed[o].sum() for o in t.types))
        for o in t.types:
            k = t.K[o][o]
            ok = np.flatnonzero(t.allowed[o])
            self.assertTrue((k >= 0).all())
            self.assertTrue(all(k[c, c] >= k[c, ok].max() - 1e-9 for c in ok))   # a die heats itself most

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
            self.assertEqual(notes['kernel_solves'], self.table.solves)
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


if __name__ == '__main__':
    unittest.main()
