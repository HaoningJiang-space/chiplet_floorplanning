import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_tap_sensitivity import sample_layouts, thermal_key, source_case
from prepare_tap_fv import make_case
from freeze_tap_geometry import verify
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.model import parse_case


class SensitivityTest(unittest.TestCase):
    def domain(self):
        return dict(name='test', interposer_side_um=50000, centre_grid_um=10000,
                    minimum_gap_um=100, rotations_deg=[0, 90, 180, 270],
                    chiplets=[dict(id=i, core_width_um=5000, core_height_um=8000,
                                   bump_ring_um=90, power_w=2+i) for i in range(2)])

    def test_sampling_reproducible_legal_and_unique(self):
        domain = self.domain()
        a, _ = sample_layouts(domain, 10, 17)
        b, _ = sample_layouts(domain, 10, 17)
        self.assertEqual(a, b)
        self.assertEqual(len({thermal_key(p) for p in a}), 10)
        for placement in a:
            verify(domain, placement)

    def test_source_isolation_preserves_operator_and_adds_rhs(self):
        domain = self.domain()
        placements, _ = sample_layouts(domain, 1, 17)
        data = make_case(domain, placements[0], resolution=8)
        original = copy.deepcopy(data)
        case = parse_case(data)
        matrix, rhs, *_ = assemble_package(case, rasterize(case)[0])
        accumulated = rhs*0
        for die in case.dies:
            single = source_case(data, die.id)
            a, b, *_ = assemble_package(single, rasterize(single)[0])
            self.assertEqual((a != matrix).nnz, 0)
            accumulated += b
        self.assertLess(abs(accumulated-rhs).max(), 1e-12)
        self.assertEqual(data, original)
