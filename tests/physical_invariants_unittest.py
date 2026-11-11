import sys
from pathlib import Path
import unittest

import numpy as np
from scipy.sparse import csr_matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.physical_invariants import heat_ledger, passive_conductance


class PhysicalInvariantTest(unittest.TestCase):
    def test_hand_solved_two_node_energy_entropy(self):
        # One W at node 1; g12=1 W/K, sink2=1 W/K -> rises [2,1] K.
        matrix = csr_matrix([[1., -1.], [-1., 2.]])
        r = heat_ledger(matrix, np.array([0., 1.]), np.array([302., 301.]), 300., np.array([1., 0.]))
        self.assertEqual(r['energy_balance_error_w'], 0)
        self.assertAlmostEqual(r['internal_entropy_production_w_per_k'], 1/(302*301))
        self.assertAlmostEqual(r['boundary_entropy_production_w_per_k'], 1/300-1/301)

    def test_active_asymmetric_and_unanchored_rejected(self):
        for matrix, sink in [([[1., 1.], [1., 1.]], [2., 2.]),
                             ([[2., -1.], [-2., 3.]], [1., 1.]),
                             ([[1., -1.], [-1., 1.]], [0., 0.]),
                             ([[2., -1.], [-1., 2.]], [0., 0.])]:
            with self.assertRaises(ValueError):
                passive_conductance(csr_matrix(matrix), sink)

    def test_disconnected_unsunk_island_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unanchored'):
            passive_conductance(csr_matrix([[1., 0.], [0., 0.]]), [1., 0.])


if __name__ == '__main__':
    unittest.main()
