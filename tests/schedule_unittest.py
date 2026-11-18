from dataclasses import replace
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from sizing_unittest import small_problem  # noqa: E402
from chiplet_floorplanning.placement import Evaluator, Layout, is_legal, pin_manhattan_um  # noqa: E402
from chiplet_floorplanning.placement import schedule  # noqa: E402


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.p = small_problem()
        self.anchor = Layout(np.array([[10., 10.], [30., 10.], [10., 30.], [30., 30.]])*1000, np.zeros(4, int))
        with Evaluator(self.p, 500, resolution=16) as evaluator:
            self.peak = evaluator.peaks_c([self.anchor])[0]
        self.limited = replace(self.p, limit_c=np.full(4, self.peak))
        self.length = pin_manhattan_um(self.p, self.anchor).sum()/1e6

    def test_the_best_design_is_certified_within_budget(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() + 300, threads=1, workers=1, resolution=16, chain_steps=3)
        self.assertLessEqual(out['fv_solves'], 200)
        best = out['best']
        sized = replace(self.limited, carrier_um=(best['width_mm']*1000, best['height_mm']*1000))
        layout = Layout(np.array(best['centre_um']), np.array(best['rotation_deg']))
        self.assertTrue(is_legal(sized, layout, 500))
        with Evaluator(sized, 500, resolution=16) as evaluator:          # independent FV re-check
            self.assertLessEqual(evaluator.peaks_c([layout])[0], 1e-6)
        self.assertLessEqual(pin_manhattan_um(sized, layout).sum()/1e6, self.length + 1e-9)
        self.assertLess(best['cost_usd'], 208.75)
        targets = [r for r in out['history'] if 'stages' in r]
        self.assertTrue(targets and all('first_certifier' in r and 'fv_total' in r for r in targets))

    def test_nothing_starts_after_the_shared_deadline(self):
        out = schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                                 deadline=time.perf_counter() - 1, resolution=16)
        self.assertEqual(out['fv_solves'], 0)
        from run_cosize import fixed_aspect                            # the baseline takes the same deadline
        with patch('run_cosize.relation_front') as search:
            base = fixed_aspect(self.limited, 500, self.length, 100, 2, 5, 1, self.anchor, resolution=16,
                                deadline=time.perf_counter() - 1)
        search.assert_not_called()
        self.assertEqual(base['history'][-1]['stop'], 'deadline')

    def test_an_ordinary_failure_is_not_a_proof(self):
        calls = []

        def fail(ctx, shape, area, deadline):
            calls.append(area)
            return dict(stages=[], certified=False, first_certifier=None, width_mm=1, height_mm=1), None
        with patch.object(schedule, 'cascade', side_effect=fail):
            schedule.scheduled(self.limited, self.anchor, 500, self.length, fv_budget=200,
                               deadline=time.perf_counter() + 60, threads=1, workers=1, resolution=16)
        first = calls[0]
        self.assertTrue(any(a < first for a in calls))                 # the lower half is still tried
        self.assertTrue(any(a > first for a in calls))                 # and towards the certified side first


if __name__ == '__main__':
    unittest.main()
