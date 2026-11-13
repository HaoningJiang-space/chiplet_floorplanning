from copy import deepcopy
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_crossover import compatible_crossover, full_key, run_policy
from atplace_pin_geometry import make_thermal_case, placement_geometry
from atplace_search import CostLimit, Space
from import_atplace_cases import parse_case as import_case
from atplace_import_unittest import BLOCKS, POWER, NETS
from run_atplace_crossover import design_signature


class CrossoverTest(unittest.TestCase):
    def setUp(self):
        self.source = dict(interposer_width_um=20000, interposer_height_um=12000,
            chiplets=[dict(name=f'd{i}', width_um=2000, height_um=2000) for i in range(6)])
        self.a = [dict(chiplet=f'd{i}', centre_x_um=(2+3*i)*1000, centre_y_um=3000,
                       rotation_deg=0) for i in range(6)]
        self.b = deepcopy(self.a)
        for i, p in enumerate(self.b):
            p['centre_x_um'] = self.a[5-i]['centre_x_um']

    def test_cross_parent_collisions_are_excluded_and_mixed_states_preferred(self):
        space = Space(self.source, 1000, 1000, 1000)
        receipt = {}
        parents_before = deepcopy((self.a, self.b, self.source))
        p = compatible_crossover(space, self.a, self.b, random.Random(7), receipt)
        placement_geometry(self.source, p, 1000)
        self.assertNotIn(full_key(p), (full_key(self.a), full_key(self.b)))
        # Three independent pair-swaps: exactly 2^3 consistent combinations.
        self.assertEqual((receipt['masks_checked'], receipt['legal_masks'],
                          receipt['distinct_mixed_states']), (64, 8, 6))
        self.assertEqual(space.checks, 64)
        self.assertEqual((self.a, self.b, self.source), parents_before)

    def test_shared_parent_genes_do_not_multiply_selection_weight(self):
        b = deepcopy(self.a)
        b[0]['rotation_deg'] = 180
        class InspectChoice:
            def choice(inner, choices):
                self.assertEqual(len(choices), 2)
                return choices[-1]
        space = Space(self.source, 1000, 1000, 1000)
        receipt = {}
        p = compatible_crossover(space, self.a, b, InspectChoice(), receipt)
        self.assertEqual(receipt['legal_masks'], 64)
        self.assertEqual(receipt['distinct_legal_states'], 2)
        self.assertEqual(receipt['distinct_mixed_states'], 0)
        self.assertEqual(receipt['selection'], 'parent_fallback')
        self.assertEqual(p[0]['rotation_deg'], 180)

    def test_identical_parents_have_one_fallback_and_still_pay_all_checks(self):
        space = Space(self.source, 1000, 1000, 64)
        receipt = {}
        p = compatible_crossover(space, self.a, self.a, random.Random(1), receipt)
        self.assertEqual(p, self.a)
        self.assertEqual(receipt['distinct_legal_states'], 1)
        self.assertEqual(receipt['distinct_mixed_states'], 0)
        self.assertEqual(space.checks, 64)

    def test_mid_enumeration_cap_does_not_select_from_a_biased_prefix(self):
        space = Space(self.source, 1000, 1000, 63)
        receipt = {}
        with self.assertRaisesRegex(CostLimit, 'candidate_check_cap'):
            compatible_crossover(space, self.a, self.b, random.Random(1), receipt)
        self.assertEqual(receipt['masks_checked'], 63)
        self.assertEqual(receipt['selection'], 'incomplete')
        self.assertNotIn('placement', receipt)

    def test_inherited_chip_identity_cannot_be_swapped(self):
        b = self.b[::-1]
        with self.assertRaisesRegex(ValueError, 'order'):
            compatible_crossover(Space(self.source, 1000, 1000, 1000), self.a, b, random.Random(1), {})

    def test_physical_signature_permits_only_rigid_pose_changes(self):
        source = import_case('test', BLOCKS, POWER, NETS)
        a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
             dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        base = make_thermal_case(source, a, 1000)
        a[0].update(centre_y_um=4000, rotation_deg=90)
        moved = make_thermal_case(source, a, 1000)
        self.assertEqual(design_signature(base), design_signature(moved))
        for key in ('power', 'size', 'boundary', 'port'):
            bad = deepcopy(moved)
            if key == 'power': bad['chiplets'][0]['blocks'][0]['power_w'] = 0
            if key == 'size': bad['chiplets'][0]['size_mm']['width'] *= .5
            if key == 'boundary': bad['thermal']['top_h_w_m2k'] *= 2
            if key == 'port': bad['chiplets'][0]['ports_mm']['n0_0']['x'] += .1
            self.assertNotEqual(design_signature(base), design_signature(bad))

    def test_search_preserves_legality_and_charges_crossover_work(self):
        source = import_case('test', BLOCKS, POWER, NETS)
        a = [dict(chiplet='a', centre_x_um=3000, centre_y_um=3000, rotation_deg=0),
             dict(chiplet='b', centre_x_um=8000, centre_y_um=6000, rotation_deg=0)]
        b = deepcopy(a)
        b[0]['centre_y_um'] += 1000
        plan = dict(seed=2026111200, gap_um=1000, grid_um=1000, population=2,
            proposal_cap=200, candidate_check_cap=100000, pin_call_cap=1000, thermal_budget=4,
            length_cap_m=.0072, temperature_cap_c=80., initialization=dict(placements=[a, b],
            construction_attempts=1, candidate_checks=0, elapsed_seconds=0.))
        result = run_policy(source, plan, lambda d: dict(numerical_admission_passed=True, peak_power_layer_c=80.))
        self.assertEqual(result['status'], 'complete_thermal_budget')
        self.assertEqual(result['effort']['illegal_proposals'], 0)
        self.assertEqual(result['effort']['illegal_context_fallbacks'], 0)
        self.assertGreater(result['effort']['crossover_mask_checks'], 0)
        for row in result['rows']:
            placement_geometry(source, row['placement'], 1000)


if __name__ == '__main__':
    unittest.main()
