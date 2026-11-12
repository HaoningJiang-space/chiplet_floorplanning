from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chiplet_floorplanning.network_sta import execute_opensta
from chiplet_floorplanning.decision import summarize_decisions


class NetworkExecutionTest(unittest.TestCase):
    def test_timeout_retains_partial_output_and_is_not_infeasible(self):
        with TemporaryDirectory() as temp:
            exe = Path(temp)/'sta.exe'
            exe.write_bytes(b'test')
            error = subprocess.TimeoutExpired(['sta'], 120, output=b'partial stdout', stderr=b'partial stderr')
            with patch('chiplet_floorplanning.network_sta.subprocess.run', side_effect=error):
                result = execute_opensta(exe, temp)
        self.assertEqual(result['execution_status'], 'timeout')
        self.assertIsNone(result['returncode'])
        self.assertIn('partial stdoutpartial stderr', result['log'])
        self.assertNotIn('timing_feasible', result)

    def test_completed_nonzero_is_distinct_from_timeout(self):
        with TemporaryDirectory() as temp:
            exe = Path(temp)/'sta.exe'
            exe.write_bytes(b'test')
            with patch('chiplet_floorplanning.network_sta.subprocess.run', return_value=subprocess.CompletedProcess([], 2, 'out', 'err')):
                result = execute_opensta(exe, temp)
        self.assertEqual(result['execution_status'], 'completed')
        self.assertEqual(result['returncode'], 2)
        self.assertEqual(result['log'], 'outerr')

    def test_timeout_cannot_enter_feasible_witness_or_empty_proof(self):
        row = dict(id='a', layout_id='a', profile='nominal', geometry_feasible=True,
                   routing_status='feasible', thermal=dict(peak_c=60),
                   timing={mode: dict(status='execution_timeout') for mode in ('reference', 'feedback')})
        summary = summarize_decisions([row], expected_layout_ids=['a'], expected_profile='nominal')
        stage = summary['stages']['timing_feedback']
        self.assertIsNone(stage['best_witness'])
        self.assertFalse(stage['empty_set_proven'])
        self.assertFalse(stage['certified_numerical_optimum'])
        self.assertIsNone(summary['timing_temperature_cost']['feedback']['exact_penalty_k'])


if __name__ == '__main__':
    unittest.main()
