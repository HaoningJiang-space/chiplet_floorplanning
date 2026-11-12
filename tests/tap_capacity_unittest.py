import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_tap_capacity import direct_witness


class PinCapacityTest(unittest.TestCase):
    def test_shared_incoming_outgoing_capacity_not_double_allocated(self):
        result = direct_witness([[1, 2], [1, 1], [2, 1]], [[0, 1, 1], [0, 0, 1], [1, 0, 0]])
        self.assertEqual(result['status'], 'feasible_in_complete_direct_pin_model')
        self.assertEqual(result['incident_demands'], [3, 2, 3])
        self.assertEqual(sum(f['amount'] for f in result['flows']), 4)

    def test_single_chiplet_cut_proves_failure(self):
        result = direct_witness([[1], [2]], [[0, 1], [1, 0]])
        self.assertEqual(result['cut_certificates'], [dict(chiplet=0, required=2, capacity=1)])

    def test_fractional_demands_not_silently_rounded(self):
        with self.assertRaises(ValueError):
            direct_witness([[2], [2]], [[0, 1.5], [0, 0]])


if __name__ == '__main__':
    unittest.main()
