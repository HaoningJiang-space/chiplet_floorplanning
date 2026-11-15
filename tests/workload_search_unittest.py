from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from workload_search import analyse, llm_power, targets  # noqa: E402
from atplace_import_unittest import BLOCKS, POWER, NETS  # noqa: E402
from import_atplace_cases import parse_case as import_case  # noqa: E402
from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um  # noqa: E402


class WorkloadSearchTest(unittest.TestCase):
    def test_llm_power_meets_the_package_share_with_one_compute_activity(self):
        names = ('CPU1_0', 'GPU_0', 'GPU_1', 'HBM_0', 'HBM_1', 'HBM_2')
        nominal = np.array([105., 300., 300., 25., 25., 25.])
        power, x = llm_power(names, nominal, total=.55, memory=1.)
        self.assertAlmostEqual(power.sum(), .55*780)
        self.assertTrue(np.allclose(power[:3], x*nominal[:3]) and np.allclose(power[3:], 25.))
        power, x = llm_power(names, nominal, total=.9, memory=.5)
        self.assertAlmostEqual(power.sum(), .9*780)
        self.assertAlmostEqual(power[3], 12.5)
        _, x = llm_power(names, nominal, total=1.2, memory=1.)
        self.assertEqual(x, 1.)  # no boost: clipped

    def test_targets_cover_declared_controls_and_llm(self):
        case10 = ('CPU1_0', 'CPU1_1', 'CPU2_0', 'GPU_0', 'GPU_1', 'IODie_0')
        self.assertEqual(sorted(targets(case10, 10)), ['budget/compute_half', 'budget/cpu_idle'])
        case1 = ('CPU1_0', 'GPU_0', 'GPU_1', 'HBM_0')
        self.assertEqual(sorted(targets(case1, 1)), ['llm/decode_hbm_full', 'llm/decode_hbm_half', 'llm/prefill'])

    def test_front_numbers_must_describe_the_layout_coordinates(self):
        # Review of 56f3af6: a 7 mm layout recorded as 5 mm passed a 6.25 mm cap.
        case = import_case('fixture', BLOCKS, POWER, NETS)
        problem = Problem.from_imported(case)
        layout = Layout(np.array([[2000., 1000.], [5500., 1000.]]), np.array([0, 0]))
        true_m = pin_manhattan_um(problem, layout).sum()/1e6
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder/'case.json').write_text(json.dumps(case))
            np.savez(folder/'layouts.npz', centre_um=layout.centre_um[None], rotation_deg=layout.rotation_deg[None],
                     length_m=np.array([true_m - 2e-3]), peak_c=np.array([50.]))
            (folder/'summary.json').write_text(json.dumps(dict(
                case='fixture', case_sha256=sha256((folder/'case.json').read_bytes()).hexdigest(),
                gap_um=0., fv_resolution=64, front=[dict(index=0, length_m=true_m - 2e-3, peak_c=50.)])))
            with self.assertRaisesRegex(SystemExit, 'lengths'):
                analyse(1, folder/'case.json', folder/'summary.json', folder/'layouts.npz', 1)


if __name__ == '__main__':
    unittest.main()
