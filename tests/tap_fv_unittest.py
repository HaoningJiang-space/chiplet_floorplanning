import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np
from scipy.sparse.linalg import spsolve
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from prepare_tap_fv import make_case
from chiplet_floorplanning.model import parse_case,ModelError
from chiplet_floorplanning.package import assemble_package,material_grids
from chiplet_floorplanning.power import rasterize


def analytic_case():
    return dict(schema_version=1,name='two_solid_column',package_mm=dict(width=2,height=2),grid=dict(nx=1,ny=1),
        chiplets=[dict(id='source',size_mm=dict(width=2,height=2),placement_mm=dict(x=0,y=0),rotation_deg=0,
            blocks=[dict(id='heat',rect_mm=dict(x=0,y=0,width=2,height=2),power_w=2,provenance='analytic control, not hardware')],ports_mm={})],
        thermal=dict(model='layered_package_steady',ambient_c=25,top_h_w_m2k=1000,bottom_h_w_m2k=0,
            power_layer='lower',provenance='analytic Fourier series network',layers=[
                dict(id='lower',thickness_mm=1,conductivity_w_mk=10,footprint='package'),
                dict(id='upper',thickness_mm=2,conductivity_w_mk=20,footprint='package')]),
        interconnect=dict(model='manhattan_lower_bound',r_ohm_per_mm=0,c_pf_per_mm=0,provenance='unused'),links=[])


class TapFVTest(unittest.TestCase):
    def test_two_layer_analytic_flux_and_external_half_cell(self):
        case=parse_case(analytic_case());power,_=rasterize(case)
        a,b,g,*_=assemble_package(case,power);theta=spsolve(a,b)
        # Independent Fourier integration from each cell centre to ambient.
        area=4e-6
        expected=[2*(.001/(2*10)+.002/20+1/1000)/area,
                  2*(.002/(2*20)+1/1000)/area]
        np.testing.assert_allclose(theta,expected,rtol=0,atol=1e-9)
        self.assertAlmostEqual(float(g@theta),2,places=12)

    def test_external_convection_cannot_modify_internal_edges(self):
        raw=analytic_case();case=parse_case(raw);p,_=rasterize(case)
        a,*_=assemble_package(case,p)
        raw['thermal']['top_h_w_m2k']=500
        changed,*_=assemble_package(parse_case(raw),p)
        self.assertEqual(a[0,1],changed[0,1]);self.assertEqual(a[1,0],changed[1,0])
        self.assertNotEqual(a[1,1],changed[1,1])

    def test_continuous_underfill_uses_harmonic_material_interface(self):
        raw=analytic_case();raw['grid']={'nx':2,'ny':1}
        raw['chiplets'][0]['size_mm']['width']=1
        raw['chiplets'][0]['blocks'][0]['rect_mm']['width']=1
        layer=raw['thermal']['layers'][0];layer['conductivity_w_mk']=1
        layer['die_materials']={'source':{'conductivity_w_mk':10}}
        case=parse_case(raw);power,_=rasterize(case)
        a,b,g,nodes,ids,z=assemble_package(case,power)
        face=.001*.002
        expected=face/(.001/(2*10)+.001/(2*1))
        self.assertAlmostEqual(-a[ids[0,0,0],ids[0,0,1]],expected,places=12)
        layer['sidewall_contacts']=[{'dies':['source','source'],'resistance_m2k_w':0}]
        with self.assertRaises(ModelError):parse_case(raw)

    def test_all_source_cases_retain_power_and_expanded_core_geometry(self):
        root=Path(__file__).resolve().parents[1]
        entries=json.loads((root/'docs/evidence/tap-geometry-domains.json').read_text())['cases']
        for entry in entries:
            d=entry['domain'];case=parse_case(make_case(d,entry['witness']['placement']))
            power,mapping=rasterize(case)
            self.assertAlmostEqual(float(power.sum()),sum(c['power_w'] for c in d['chiplets']))
            self.assertEqual(len(case.dies),len(d['chiplets']))
            for c,die in zip(d['chiplets'],case.dies):
                self.assertAlmostEqual(die.blocks[0].rect.width,c['core_width_um']/1000)
                self.assertAlmostEqual(die.blocks[0].rect.x,c['bump_ring_um']/1000)


if __name__=='__main__':unittest.main()
