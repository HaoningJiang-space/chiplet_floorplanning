import copy
from pathlib import Path
import random
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from tap_online import Space, run_policy
from diagnose_tap_sensitivity import thermal_key
from verify_tap_online_pilot import independent_metrics, validate_run


class PilotVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.domain = dict(name='test', interposer_side_um=50000, centre_grid_um=10000,
            minimum_gap_um=100, rotations_deg=[0, 90, 180, 270],
            chiplets=[dict(id=i, core_width_um=5000, core_height_um=8000,
                           bump_ring_um=90, power_w=2+i) for i in range(2)],
            connection_wire_demands=[[0, 1], [1, 0]])
        scale = dict(temperature_origin_c=70, temperature_scale_k=10, span_origin_mm=0,
                     span_scale_mm=50, hypervolume_reference=[1.2, 1.2])
        space, rng = Space(cls.domain), random.Random(711)
        initial, seen = [], set()
        while len(initial) < 16:
            p = space.construct(rng)
            if p is not None and thermal_key(p) not in seen:
                initial.append(p)
                seen.add(thermal_key(p))
        cls.plan = dict(budget=64, proposal_cap=10000, hits_commit='synthetic-test-fixture')
        cls.entry = dict(domain=cls.domain, scale=scale, initializations=[dict(seed=19, placements=initial)])
        def solve(p):
            return dict(peak_power_layer_c=70+p[0]['centre_x_um']/10000,
                source_power_w=5., mapped_power_w=5., heat_removed_w=5., energy_balance_error_w=0.,
                original_relative_residual=0., max_reference_difference_k=0., min_rise_k=0.,
                max_internal_coefficient_change_w_k=0., max_asymmetry_w_k=0., max_offdiagonal_w_k=-1.,
                numerical_admission_passed=True, hits_receipt=dict(accepted=True))
        cls.result = run_policy(cls.domain, initial, scale, 'random', 19, solve)
        cls.result.update(smoke_only=False, scale=scale, hits_commit=cls.plan['hits_commit'])

    def test_complete_synthetic_ledger_and_replay(self):
        self.assertTrue(validate_run(self.result, self.entry, self.plan, replay=True))

    def test_unseen_cache_reference_is_rejected(self):
        bad = copy.deepcopy(self.result)
        bad['events'][0]['status'] = 'cache_hit'
        with self.assertRaisesRegex(ValueError, 'unseen'):
            validate_run(bad, self.entry, self.plan)

    def test_changed_power_or_objective_is_rejected(self):
        bad = copy.deepcopy(self.result)
        bad['rows'][0]['thermal']['source_power_w'] = 6.
        with self.assertRaisesRegex(ValueError, 'Thermal evidence'):
            validate_run(bad, self.entry, self.plan)
        bad = copy.deepcopy(self.result)
        bad['rows'][-1]['centre_span_mm'] += 1
        with self.assertRaisesRegex(ValueError, 'Centre span'):
            validate_run(bad, self.entry, self.plan)

    def test_false_metric_and_completion_are_rejected(self):
        bad = copy.deepcopy(self.result)
        bad['checkpoints'][0]['hypervolume'] += .1
        with self.assertRaisesRegex(ValueError, 'Metric mismatch'):
            validate_run(bad, self.entry, self.plan)
        bad = copy.deepcopy(self.result)
        bad['queries'] = 63
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            validate_run(bad, self.entry, self.plan)

    def test_independent_strip_integration_has_known_union(self):
        scale = dict(temperature_origin_c=0, temperature_scale_k=1, span_origin_mm=0,
                     span_scale_mm=1, hypervolume_reference=[2, 2])
        rows = [dict(peak_c=t, centre_span_mm=s) for t, s in [(0, 1), (1, 0), (3, -1)]]
        result = independent_metrics(rows, scale)
        self.assertEqual(result['hypervolume'], 3.)
        self.assertEqual(result['archive_points_outside_reference'], 1)
