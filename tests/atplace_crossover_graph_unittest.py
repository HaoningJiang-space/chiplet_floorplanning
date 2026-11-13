from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_atplace_crossover import allowed, components, implications


class ImplicationGraphTest(unittest.TestCase):
    def test_one_way_conflict_has_three_masks_and_correct_implication_direction(self):
        a = [(0, 0, 1, 1), (3, 0, 4, 1)]
        b = [(0, 3, 1, 4), (.5, 0, 1.5, 1)]
        edges = implications(a, b, 0)
        self.assertEqual(edges, [(1, 0)])
        self.assertEqual([m for m in range(4) if allowed(m, edges)], [0, 1, 3])
        self.assertEqual(components(2, edges), [[0], [1]])

    def test_swapped_locations_force_joint_inheritance(self):
        a = [(0, 0, 1, 1), (3, 0, 4, 1)]
        edges = implications(a, a[::-1], 1)
        self.assertEqual(components(2, edges), [[0, 1]])
        self.assertEqual([m for m in range(4) if allowed(m, edges)], [0, 3])


if __name__ == '__main__':
    unittest.main()
