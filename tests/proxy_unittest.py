from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, is_legal  # noqa: E402
from chiplet_floorplanning.placement.lp import milp_relations  # noqa: E402
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

    def test_proxy_milp_cools_the_proxy_and_respects_its_cap(self):
        p = small_problem()
        short = milp_relations(p, 500, 20)
        cool = milp_relations(p, 500, 20, proxy=(MODEL, None))
        self.assertLess(MODEL.peak_c(p, cool), MODEL.peak_c(p, short))
        cap = (MODEL.peak_c(p, cool) + MODEL.peak_c(p, short))/2
        capped = milp_relations(p, 500, 20, proxy=(MODEL, cap))
        # Axis separation <= true distance makes the MILP's proxy conservative; the tangents underestimate g by at
        # most `slack` per watt, so the exact proxy can exceed the cap by at most max_i sum_j P_j slack.
        r = np.linspace(3.0, np.hypot(40, 40), 2000)
        a, b = MODEL.tangents(min(np.add.outer(p.size_um.min(1), p.size_um.min(1)).ravel())/2000 + 0.5, np.hypot(40, 40))
        slack = np.max(MODEL.g(r) - (a[None] + b[None]*r[:, None]).max(axis=1))
        self.assertLessEqual(MODEL.peak_c(p, capped), cap + slack*(p.power_w.sum() - p.power_w.min()) + 1e-6)
        self.assertGreaterEqual(MODEL.peak_c(p, capped), MODEL.peak_c(p, cool) - 1e-6)

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
