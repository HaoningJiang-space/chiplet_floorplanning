import itertools
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_ihp_tap_attachment import clique_side, strip_bound, capacity_bound


class AttachmentBoundTest(unittest.TestCase):
    def test_block_clique_strict_boundary(self):
        self.assertEqual(clique_side(45000, 74990), 2)
        self.assertEqual(clique_side(45000, 129990), 3)
        # A diagonal exactly at the allowed distance must not become a clique.
        self.assertEqual(clique_side(5, 7), 1)
        with self.assertRaises(ValueError):
            clique_side(0, 75)

    def test_bound_against_exhaustive_small_independent_sets(self):
        for nx, ny, separation in [(3, 3, 75), (4, 2, 95), (3, 3, 130), (3, 2, 45)]:
            sites = list(itertools.product(range(nx), range(ny)))
            maximum = 0
            for mask in range(1 << len(sites)):
                selected = [p for i,p in enumerate(sites) if mask & (1 << i)]
                if all(45**2*((a[0]-b[0])**2+(a[1]-b[1])**2) >= separation**2
                       for a,b in itertools.combinations(selected,2)):
                    maximum = max(maximum, len(selected))
            self.assertLessEqual(maximum, strip_bound(nx,ny,clique_side(45,separation)))

    def test_ring_strip_upper_bound_and_orientation_invariance(self):
        chip = dict(core_width_um=14500, core_height_um=31400, bump_ring_um=90)
        result = capacity_bound(chip,74990)
        self.assertEqual(result['site_count'],4092)
        self.assertEqual(result['populated_sites_upper_bound'],1024)
        rotated = dict(chip, core_width_um=31400, core_height_um=14500)
        self.assertEqual(result,capacity_bound(rotated,74990))


if __name__ == '__main__':
    unittest.main()
