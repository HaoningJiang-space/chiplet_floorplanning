import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_tap_ihp_endpoints import build,verify,ring_cells,signal_capacity
from freeze_tap_ihp_geometry import placed_pad,geometry_proxy
from freeze_tap_geometry import first_fit,verify as verify_geometry


class EndpointGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.domains=[c['domain'] for c in json.loads((root/'docs/evidence/tap-geometry-domains.json').read_text())['cases']]

    def test_exact_capacity_for_odd_and_even_core_grids(self):
        for nx in range(1,6):
            for ny in range(1,6):
                for rows in range(1,4):
                    self.assertEqual(signal_capacity(nx,ny,rows),sum((x+y)%2==0 for x,y in ring_cells(nx,ny,rows)))

    def test_all_source_families_preserve_identity_and_power(self):
        for domain in self.domains:
            result=build(domain); summary=verify(domain,result)
            self.assertFalse(summary['physical_qualified'])
            self.assertEqual(sum(c['sites_by_role']['signal'] for c in summary['chips']),
                             2*sum(sum(r) for r in domain['connection_wire_demands']))
            self.assertEqual(sum(c['core_power_w'] for c in result['chips']),
                             sum(c['power_w'] for c in domain['chiplets']))

    def test_geometric_and_identity_corruption_rejected(self):
        domain=self.domains[0]; original=build(domain)
        for kind in ('duplicate','offgrid','missing','wrong_endpoint','lost_pdn','power'):
            result=copy.deepcopy(original);chip=result['chips'][0]
            if kind=='duplicate':chip['pads'].append(copy.deepcopy(chip['pads'][0]))
            if kind=='offgrid':chip['pads'][0]['x_nm']+=1
            if kind=='missing':chip['pads'].pop()
            if kind=='wrong_endpoint':
                next(p for p in chip['pads'] if p['role']=='signal')['wire']=[0,1,99999]
            if kind=='lost_pdn':
                next(p for p in chip['pads'] if p['role']=='reserved_pdn')['role']='unpopulated'
            if kind=='power':chip['core_power_w']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(domain,result)

    def test_four_rotations_use_assembly_facing_frame(self):
        chip=dict(width_nm=300000,height_nm=450000)
        pad=dict(x_nm=37500,y_nm=37500)
        expected=[(-112500,-187500),(187500,-112500),(112500,187500),(-187500,112500)]
        for rotation,point in zip((0,90,180,270),expected):
            self.assertEqual(placed_pad(chip,dict(centre_x_um=0,centre_y_um=0,rotation_deg=rotation),pad),point)

    def test_new_envelopes_fit_as_independent_full_systems(self):
        for source in self.domains:
            endpoint=build(source);domain=geometry_proxy(source,endpoint)
            witness=first_fit(domain)
            self.assertEqual(witness['status'],'geometry_feasible')
            verify_geometry(domain,witness['placement'])


if __name__=='__main__':unittest.main()
