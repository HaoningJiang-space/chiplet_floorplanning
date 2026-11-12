import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from freeze_tap_geometry import box, verify, first_fit, separated


class TapGeometryTest(unittest.TestCase):
    def domain(self):
        return dict(interposer_side_um=10000, centre_grid_um=1000, minimum_gap_um=100,
                    rotations_deg=[0, 90, 180, 270], chiplets=[
                        dict(id=i, core_width_um=3000, core_height_um=1000, bump_ring_um=500)
                        for i in range(2)])

    def p(self, i, x, y, rotation=0):
        return dict(id=i, centre_x_um=x, centre_y_um=y, rotation_deg=rotation)

    def test_rotated_bump_envelope_and_boundary(self):
        d = self.domain()
        self.assertEqual(box(d, self.p(0, 1000, 2000, 90)), (0, 0, 4000, 8000))
        with self.assertRaises(ValueError):
            box(d, self.p(0, 1000, 2000, 0))

    def test_core_clearance_does_not_imply_ring_clearance(self):
        with self.assertRaises(ValueError):
            verify(self.domain(), [self.p(0, 2000, 2000), self.p(1, 6000, 2000)])
        self.assertTrue(separated((0, 0, 2000, 2000), (2200, 0, 4200, 2000), 100))
        self.assertFalse(separated((0, 0, 2000, 2000), (2199, 0, 4199, 2000), 100))

    def test_identity_and_grid_required(self):
        with self.assertRaises(ValueError):
            verify(self.domain(), [self.p(0, 2000, 2000), self.p(0, 7000, 2000)])
        with self.assertRaises(ValueError):
            box(self.domain(), self.p(0, 2500, 2000))

    def test_witness_and_failed_search_have_distinct_status(self):
        d = self.domain()
        self.assertEqual(first_fit(d)['status'], 'geometry_feasible')
        d['interposer_side_um'] = 3000
        self.assertEqual(first_fit(d)['status'], 'search_failed_unknown')


if __name__ == '__main__':
    unittest.main()
