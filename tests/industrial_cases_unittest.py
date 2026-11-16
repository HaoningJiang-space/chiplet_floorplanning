from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from chiplet_floorplanning.placement import Problem, is_legal, pin_manhattan_um, thermal_case_data  # noqa: E402
from industrial_cases import (GAP_UM, MARGIN_UM, SLACK, case_json, footprint, g1, g2, hand_layout,  # noqa: E402
                              hbm_link_mm, outcome)


def built(spec, carrier=None):
    case = case_json(spec, carrier or spec['tight_um'] or tuple(footprint(spec['dies']) + 2*MARGIN_UM))
    return case, Problem.from_imported(case), hand_layout(case)


class IndustrialCasesTest(unittest.TestCase):
    def test_hand_layouts_are_legal_in_both_carriers_with_declared_sizes(self):
        for spec, tight in ((g1(), (50000, 48000)), (g2(), (50000, 151800))):
            for carrier in (tight, tuple(np.round(np.array(tight)*SLACK, -1))):
                case, problem, hand = built(spec, carrier)
                self.assertTrue(is_legal(problem, hand, GAP_UM), (spec['name'], carrier))
            self.assertEqual(tuple(built(spec)[0][k] for k in ('interposer_width_um', 'interposer_height_um')), tight)

    def test_net_counts_follow_bandwidth_and_hand_links_are_one_gap_long(self):
        for spec, nets, power in ((g1(), 5*34, 540 + 5*22), (g2(), 16*100 + 3*500 + 4*90, 4*750 + 16*25 + 2*60)):
            case, problem, hand = built(spec)
            self.assertEqual(len(case['nets']), nets)
            self.assertAlmostEqual(problem.power_w.sum(), power)
            self.assertAlmostEqual(hbm_link_mm(problem, hand), GAP_UM/1000)
        _, problem, hand = built(g2())
        names = np.array(problem.names)[problem.pin_chip]
        d2d = (np.char.startswith(names, 'GPU')).all(axis=1)
        np.testing.assert_allclose(pin_manhattan_um(problem, hand)[d2d], GAP_UM)

    def test_outcome_rules(self):
        hand = (10.0, 90.0)
        self.assertEqual(outcome([(10.0, 88.9)], hand)['outcome'], 'better')
        self.assertEqual(outcome([(8.9, 90.0)], hand)['outcome'], 'better')
        self.assertEqual(outcome([(10.05, 90.4)], hand)['outcome'], 'recovered')
        self.assertEqual(outcome([(10.2, 89.0), (9.0, 95.0)], hand)['outcome'], 'worse')
        self.assertIsNone(outcome([(11.0, 95.0)], hand)['d_t_k'])

    def test_calibrated_h_is_carried_and_spreader_grows_only_for_large_carriers(self):
        case, problem, hand = built(g1())
        layers = lambda data: {l['id']: l for l in data['thermal']['layers']}
        data = thermal_case_data(problem, hand, GAP_UM, 16)
        self.assertEqual(layers(data)['spreader']['rect_mm']['width'], 100)
        self.assertAlmostEqual(data['thermal']['top_h_w_m2k'], 1/(.1*.06**2))
        case['top_h_w_m2k'] = 5000.0
        self.assertEqual(thermal_case_data(Problem.from_imported(case), hand, GAP_UM, 16)['thermal']['top_h_w_m2k'], 5000.0)
        self.assertEqual(thermal_case_data(replace(problem, top_h_w_m2k=5000.0), hand, GAP_UM, 16, top_h_w_m2k=7000.0)
                         ['thermal']['top_h_w_m2k'], 7000.0)
        _, big, big_hand = built(g2())
        self.assertAlmostEqual(layers(thermal_case_data(big, big_hand, GAP_UM, 16))['spreader']['rect_mm']['width'], 171.8)
        with self.assertRaises(ValueError):
            thermal_case_data(replace(big, carrier_um=(50000.0, 185000.0)), big_hand, GAP_UM, 16)

    def test_assess_a_front_holding_only_the_hand_layout(self):
        import hashlib
        import json
        import tempfile
        from types import SimpleNamespace
        from chiplet_floorplanning.placement import Evaluator
        from industrial_cases import RESOLUTION, assess
        case, problem, hand = built(g1())
        case['name'], case['top_h_w_m2k'] = 'G1_test', 7000.0
        problem = Problem.from_imported(case)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d/'cases').mkdir()
            (d/'cases'/'G1_test.json').write_text(json.dumps(case))
            with Evaluator(problem, GAP_UM, RESOLUTION) as evaluator:
                peak, die = float(evaluator.peaks_c([hand])[0]), evaluator.die_peaks_c([hand])[0]
            length = float(pin_manhattan_um(problem, hand).sum()/1e6)
            run = d/'runs'/'G1_test'
            run.mkdir(parents=True)
            summary = dict(case='G1_test', case_sha256=hashlib.sha256((d/'cases'/'G1_test.json').read_bytes()).hexdigest(),
                           front=[dict(index=0, length_m=length, peak_c=peak, die_peak_c=dict(zip(problem.names, map(float, die))))])
            (run/'summary.json').write_text(json.dumps(summary))
            np.savez(run/'layouts.npz', centre_um=hand.centre_um[None], rotation_deg=hand.rotation_deg[None],
                     length_m=np.array([length]), peak_c=np.array([peak]))
            assess(SimpleNamespace(cases=d/'cases', runs=d/'runs', output=d/'out.json'))
            row = json.loads((d/'out.json').read_text())['cases']['G1_test']
        self.assertEqual((row['outcome'], row['d_t_k'], row['d_l']), ('recovered', 0.0, 0.0))
        self.assertAlmostEqual(row['hand']['gpu_peak_c'], row['coolest_within_1x']['gpu_peak_c'])
        self.assertAlmostEqual(row['hand']['hbm_link_mm'], 0.2)


if __name__ == '__main__':
    unittest.main()
