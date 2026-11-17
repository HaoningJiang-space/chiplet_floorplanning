from pathlib import Path
from dataclasses import replace
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, Problem, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement.lp import cluster_length_mm, milp_relations  # noqa: E402
from chiplet_floorplanning.placement.methods import Run, proxy_space  # noqa: E402
from chiplet_floorplanning.placement.proxy import R_MM, ThermalProxy  # noqa: E402

MODEL = ThermalProxy(np.array([1.2, 1.5, 1.0, 1.6]), 20.0, 1.0, 0)


class ProxyTest(unittest.TestCase):
    def test_tangents_bound_the_convex_mutual_heating_from_below(self):
        a, b = MODEL.tangents(4.0, 60.0)
        r = np.linspace(4.0, 60.0, 400)
        envelope = (a[None] + b[None]*r[:, None]).max(axis=1)
        self.assertTrue((envelope <= MODEL.g(r) + 1e-12).all())
        self.assertLess(np.max(MODEL.g(r) - envelope)/MODEL.g(4.0), 0.02)    # 12 tangents: tight
        self.assertTrue((b < 0).all())

    def test_proxy_milp_cools_the_envelope_and_respects_its_cap(self):
        p = small_problem()
        short = milp_relations(p, 500, 20)
        cool = milp_relations(p, 500, 20, proxy=(MODEL, None))
        self.assertLess(MODEL.envelope_value(p, cool, 500), MODEL.envelope_value(p, short, 500))
        cap = (MODEL.envelope_value(p, cool, 500) + MODEL.envelope_value(p, short, 500))/2
        capped = milp_relations(p, 500, 20, proxy=(MODEL, cap))
        self.assertIsNotNone(capped)
        self.assertLessEqual(MODEL.envelope_value(p, capped, 500), cap + 1e-6)

    def test_dense_cap_schedule_has_feasible_caps_in_the_solved_model(self):
        # 3e9238b used radial endpoints: three of four caps were below the axial model's provable minimum.
        p = Problem('dense', tuple('abcd'), np.array([[6000., 6000.]]*4), np.array([50.]*4), (13000., 13000.),
                    np.array([[0, 1], [1, 2], [2, 3], [3, 0]]), np.zeros((4, 2, 2)))
        start = Layout(np.array([[9000., 9000.], [9000., 3000.], [3000., 3000.], [3000., 9000.]]), np.zeros(4, int))
        with Evaluator(p, 0, resolution=64) as evaluator:
            run = Run(evaluator, 60)
            proxy_space(run, [start], np.random.default_rng(0), milp_s=5, anneal_steps=10, chains=2,
                        levels=4, cap_milp_s=5, batch=4, steps=2, caps=2)
            rows = run.notes['proxy']['results'][1:]
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(r['solved'] and r['legal'] for r in rows))
            # Legalisation rounds centres to um, so its post-snap envelope may slightly exceed the solved cap.
            self.assertLess(max(r['envelope_value'] - r['cap'] for r in rows), 0.002)
            self.assertLessEqual(evaluator.solves, 60)

    def test_limits_include_unpowered_observers_and_allow_negative_margin(self):
        p = Problem('cold_observer', ('hot', 'cold'), np.array([[6000., 6000.]]*2), np.array([10., 0.]),
                    (30000., 30000.), np.array([[0, 1]]), np.zeros((1, 2, 2)), limit_c=np.array([100., 45.5]))
        model = ThermalProxy(np.array([1., 1.]), 20., -1., 0)
        cool = milp_relations(p, 0, 5, proxy=(model, -0.1))
        self.assertIsNotNone(cool)
        self.assertLessEqual(model.envelope_value(p, cool, 0), -0.1 + 1e-6)
        relaxed = replace(p, limit_c=np.array([100., 100.]))
        near = milp_relations(relaxed, 0, 5, proxy=(model, -0.1))
        self.assertGreater(pin_manhattan_um(p, cool).sum(), pin_manhattan_um(p, near).sum() + 1000)
        self.assertAlmostEqual(model.value(replace(p, limit_c=p.limit_c + 10), cool), model.value(p, cool) - 10)
        self.assertAlmostEqual(model.envelope_value(replace(p, limit_c=p.limit_c + 10), cool, 0),
                               model.envelope_value(p, cool, 0) - 10)

    def test_method_reports_overshoot_separately_from_physical_temperature(self):
        p = Problem('limited', ('hot', 'cold'), np.array([[6000., 6000.]]*2), np.array([10., 0.]),
                    (30000., 30000.), np.array([[0, 1]]), np.zeros((1, 2, 2)), limit_c=np.array([95., 85.]))
        with Evaluator(p, 0, resolution=16) as evaluator:
            run = Run(evaluator, 30)
            proxy_space(run, [], np.random.default_rng(0), milp_s=3, anneal_steps=2, chains=1,
                        levels=1, cap_milp_s=3, batch=2, steps=1, caps=1)
            notes = run.notes['proxy']
            self.assertEqual(notes['thermal_kind'], 'overshoot_k')
            capped = notes['results'][1]
            self.assertTrue(capped['legal'])
            self.assertLess(capped['cap'], 0)
            self.assertIsNone(capped['cap_c'])
            self.assertLess(capped['fv_value'], 0)
            self.assertGreater(capped['fv_peak_c'], 45)
            self.assertLessEqual(evaluator.solves, 30)

    def test_polygonal_distance_milp_is_conservative_to_the_euclidean_proxy(self):
        p = small_problem()
        cool = milp_relations(p, 500, 20, proxy=(MODEL, None), directions=8)
        axial = milp_relations(p, 500, 20, proxy=(MODEL, None))
        # The polygonal rho is a lower bound of the centre distance, so the value at the layout is at least the
        # Euclidean proxy (up to the tangent slack), and the MILP optimum is no worse in its own metric.
        r = np.linspace(3.0, np.hypot(40, 40), 2000)
        a, b = MODEL.tangents(min(np.add.outer(p.size_um.min(1), p.size_um.min(1)).ravel())/2000 + 0.5, np.hypot(40, 40))
        slack = np.max(MODEL.g(r) - (a[None] + b[None]*r[:, None]).max(axis=1))*p.power_w.sum()
        self.assertGreaterEqual(MODEL.polygon_value(p, cool, 500, 8) + slack, MODEL.value(p, cool) - 1e-6)
        self.assertLessEqual(MODEL.polygon_value(p, cool, 500, 8), MODEL.polygon_value(p, axial, 500, 8) + 1e-6)
        warm = milp_relations(p, 500, 20, proxy=(MODEL, None), directions=8, start=axial)   # Gurobi only uses it
        self.assertLessEqual(MODEL.polygon_value(p, warm, 500, 8), MODEL.polygon_value(p, axial, 500, 8) + 1e-6)
        d = np.array([3.0, 4.0])
        angles = 2*np.pi*np.arange(8)/8
        support = (np.stack((np.cos(angles), np.sin(angles)), axis=1) @ d).max()
        self.assertTrue(5*np.cos(np.pi/8) - 1e-9 <= support <= 5 + 1e-9)

    def test_wire_budget_bounds_the_clustered_length_in_the_milp_units(self):
        p = small_problem()
        short = milp_relations(p, 500, 20)
        cool = milp_relations(p, 500, 20, proxy=(MODEL, None))
        low, high = cluster_length_mm(p, short), cluster_length_mm(p, cool)
        self.assertLessEqual(low, pin_manhattan_um(p, short).sum()/1000 + 1e-6)     # clustered: a lower bound
        self.assertLess(low, high)
        budget = (low + high)/2
        mid = milp_relations(p, 500, 20, proxy=(MODEL, None, budget))
        self.assertLessEqual(cluster_length_mm(p, mid), budget + 1e-3)
        # The shortest layout is a witness of the budget, so the minimised envelope cannot be worse than its own.
        self.assertLessEqual(MODEL.envelope_value(p, mid, 500), MODEL.envelope_value(p, short, 500) + 1e-6)
        self.assertGreaterEqual(MODEL.envelope_value(p, mid, 500), MODEL.envelope_value(p, cool, 500) - 1e-6)

    def test_length_sweep_records_budgets_and_archive_indices(self):
        p = small_problem()
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 60)
            proxy_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, levels=2,
                        cap_milp_s=10, batch=4, sweep='length')
            notes = run.notes['proxy']
            self.assertEqual(notes['sweep'], 'length')
            rows = notes['results']
            self.assertIsNone(rows[0]['budget_mm'])
            self.assertTrue(all(r['budget_mm'] is not None and r['solved'] for r in rows[1:]))
            for r in rows:
                if r['legal'] and r['layout_index'] is not None:
                    self.assertEqual(run.peaks[r['layout_index']], r['fv_value'])
            self.assertLessEqual(evaluator.solves, 60)

    def test_calibration_cost_and_the_method_budget(self):
        p = small_problem()
        model = ThermalProxy.calibrate(p, 500, resolution=16)
        self.assertEqual(model.solves, len(R_MM) + len({tuple(s) for s in p.size_um}))
        self.assertGreater(model.lam_mm, 5)
        self.assertTrue((model.self_k_w > 0).all())
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 60)
            proxy_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, levels=2,
                        cap_milp_s=10, batch=4)
            notes = run.notes['proxy']
            self.assertNotIn('skipped', notes)
            self.assertEqual(len(notes['results']), 3)
            self.assertTrue(all(r['fv_peak_c'] is not None for r in notes['results'] if r['legal']))
            self.assertLessEqual(evaluator.solves, 60)
            self.assertTrue(run.layouts and all(is_legal(p, l, 500) for l in run.layouts))
        with Evaluator(p, 500, resolution=16) as evaluator:
            run = Run(evaluator, 8)
            proxy_space(run, [], np.random.default_rng(0), milp_s=10, anneal_steps=10, chains=2, batch=4)
            self.assertIn('skipped', run.notes['proxy'])
            self.assertLessEqual(evaluator.solves, 8)


if __name__ == '__main__':
    unittest.main()
