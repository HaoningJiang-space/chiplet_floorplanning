"""Transfer TAP sourced parameters into the existing cell-centred package model."""
import argparse
import json
from pathlib import Path
from freeze_tap_geometry import box, verify
from chiplet_floorplanning.model import parse_case

PROVENANCE = 'TAP 3a3f4e5 passive_interposer.py; explicit FV research model, not HotSpot reproduction or measured calibration'


def make_case(domain, placements, resolution=64):
    verify(domain,placements)
    if domain['interposer_side_um'] != 50000:
        raise ValueError('Only the sourced 50 mm package family is transferred')
    chips=[]
    for p in sorted(placements,key=lambda p:p['id']):
        c=domain['chiplets'][p['id']];ring=c['bump_ring_um']/1000
        w,h=c['core_width_um']/1000,c['core_height_um']/1000
        bounds=box(domain,p)
        # Canonicalize only the declared centred uniform-core thermal model.
        # Routing keeps the original four-way orientation and actual bump map.
        chips.append(dict(id='chip'+str(p['id']),size_mm=dict(width=w+2*ring,height=h+2*ring),
            placement_mm=dict(x=75+bounds[0]/2000,y=75+bounds[1]/2000),rotation_deg=p['rotation_deg']%180,
            blocks=[dict(id='core',rect_mm=dict(x=ring,y=ring,width=w,height=h),power_w=c['power_w'],provenance=PROVENANCE)],ports_mm={}))
    def layer(name,t,k,side=50,materials=None):
        d=dict(id=name,thickness_mm=t,conductivity_w_mk=k,footprint='rectangle',rect_mm=dict(x=(200-side)/2,y=(200-side)/2,width=side,height=side))
        if materials is not None:d['die_materials']={c['id']:dict(conductivity_w_mk=materials) for c in chips}
        return d
    # Preserve TAP's square area fraction convention, not a circular bump inference.
    mixture=lambda diameter,pitch,background:400*(diameter/pitch)**2+background*(1-(diameter/pitch)**2)
    layers=[layer('substrate',.2,1/3.33),layer('c4',.07,mixture(250,600,1.6)),
        layer('interposer',.11,mixture(10,50,100)),layer('microbumps',.01,1.6,materials=mixture(25,45,1.6)),
        layer('dies',.15,1.6,materials=100),layer('tim',.02,4),layer('spreader',1,400,100),layer('sink',6.9,400,200)]
    data=dict(schema_version=1,name='tap_fv_'+domain['name'],package_mm=dict(width=200,height=200),
        grid=dict(nx=resolution,ny=resolution,mode='geometry_conformal'),chiplets=chips,
        thermal=dict(model='layered_package_steady',ambient_c=45,top_h_w_m2k=1/(.1*.06**2),bottom_h_w_m2k=0,
            power_layer='dies',provenance=PROVENANCE,layers=layers),
        interconnect=dict(model='manhattan_lower_bound',r_ohm_per_mm=0,c_pf_per_mm=0,
            provenance='Unused schema fields: links empty; no routing/timing model or zero-cost interconnect claim'),links=[])
    parse_case(data)
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domains',type=Path,default=Path('docs/evidence/tap-geometry-domains.json'))
    p.add_argument('--case',choices=['ascend910','micro150','multigpu'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resolution',type=int,default=64)
    args=p.parse_args()
    entry=next(c for c in json.loads(args.domains.read_text())['cases'] if c['domain']['name']==args.case)
    data=make_case(entry['domain'],entry['witness']['placement'],args.resolution)
    with args.output.open('x') as f:json.dump(data,f,indent=2);f.write('\n')
    case=parse_case(data)
    print(json.dumps(dict(name=case.name,mesh=[case.nx,case.ny],power_w=sum(b.power_w for d in case.dies for b in d.blocks))))


if __name__=='__main__':main()
