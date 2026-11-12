import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from freeze_tap_decision_domain import small_choices,enumerate_small,physical_geometry_key,full_width_cut_bound
from freeze_tap_geometry import verify
from prepare_tap_fv import make_case
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import material_grids

class TapDecisionDomainTest(unittest.TestCase):
    def source(self):
        root=Path(__file__).resolve().parents[1]
        return json.loads((root/'docs/evidence/tap-geometry-domains.json').read_text())['cases'][0]

    def test_domain_preserves_independent_choices_and_all_rotations(self):
        e=self.source();d=e['domain'];choices=small_choices(d,e['witness']['placement'])
        self.assertEqual(len(choices),6)
        rotated=[dict(p,centre_x_um=d['interposer_side_um']-p['centre_y_um'],centre_y_um=p['centre_x_um'],rotation_deg=90) for p in e['witness']['placement']]
        verify(d,rotated)
        self.assertTrue(all(p in choices[i] for i,p in enumerate(rotated)))
        self.assertEqual({p['rotation_deg'] for options in choices for p in options},{0,90,180,270})

    def test_half_turn_reuse_covers_actual_power_and_material_fields(self):
        e=self.source();d=e['domain'];a=e['witness']['placement'];b=[dict(p,rotation_deg=(p['rotation_deg']+180)%360) for p in a]
        self.assertEqual(physical_geometry_key(d,a),physical_geometry_key(d,b))
        ca,cb=(parse_case(make_case(d,p)) for p in (a,b))
        np.testing.assert_allclose(ca.mesh.x_edges_mm,cb.mesh.x_edges_mm,rtol=0,atol=1e-12)
        np.testing.assert_allclose(ca.mesh.y_edges_mm,cb.mesh.y_edges_mm,rtol=0,atol=1e-12)
        np.testing.assert_allclose(rasterize(ca)[0],rasterize(cb)[0],rtol=1e-10,atol=1e-12)
        for left,right in zip(material_grids(ca)[1:3],material_grids(cb)[1:3]):
            for x,y in zip(left,right):np.testing.assert_array_equal(x,y)

    def test_full_cut_is_only_a_necessary_bound(self):
        d=self.source()['domain'];r=full_width_cut_bound(d)
        self.assertFalse(r['any_single_full_width_cut_can_reject'])
        self.assertEqual(r['full_width_track_capacity'],25000)
        changed=copy.deepcopy(d);changed['connection_wire_demands'][0][1]=30000
        # True means the upper bound no longer rules out rejection, not that
        # this or any placement is actually infeasible.
        self.assertTrue(full_width_cut_bound(changed)['any_single_full_width_cut_can_reject'])
        with self.assertRaises(ValueError):full_width_cut_bound(d,0)

if __name__=='__main__':unittest.main()
