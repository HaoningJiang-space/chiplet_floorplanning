"""Hydraulic checks, independent coupon comparison and a fixed-layout direction test."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy import sparse

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.microchannels import Channels, CP, RHO, conjugate, duct_resistance, hydraulics
from chiplet_floorplanning.placement.thermal import thermal_case_data
from chiplet_floorplanning.power import rasterize
from compare_large_pool import write_json
from continuous_baseline_audit import escape_util
from continuous_reach_geometry import inspect


PUMP_W, INLET_C = .20, 25.
PLATE = Channels()
DIRECTIONS = ('forward','reverse')
EVIDENCE = Path(__file__).resolve().parents[1]/'docs/evidence'
LAYOUTS = EVIDENCE/'flow-reversal-layouts.json'


def coupon():
    """One symmetric pitch of the Qu/Mudawar copper coupon, 100 W/cm², figures 4/5/7."""
    plate = Channels(count=1,length_m=.044764)
    nx,nz = 120,16
    pitch = plate.pitch_m
    dx,dz = plate.length_m/nx,.005637/nz
    ids = np.arange(nx*nz).reshape(nz,nx)
    a = np.r_[ids[:,:-1].ravel(),ids[:-1].ravel()]
    b = np.r_[ids[:,1:].ravel(),ids[1:].ravel()]
    k = 401.
    g = np.r_[np.full((nx-1)*nz,k*dz*pitch/dx),np.full(nx*(nz-1),k*dx*pitch/dz)]
    edges = sparse.coo_matrix((g,(a,b)),shape=(nx*nz,nx*nz)).tocsr()
    edges += edges.T
    solid = sparse.diags(np.asarray(edges.sum(axis=1)).ravel())-edges
    load = np.zeros(nx*nz)
    total_w = 448.  # experimental 1 x 4.48 cm planform, 21 channels
    load[ids[-1]] = total_w/(21*nx)
    mean_flow = []
    for re,dp_read,out_read,wall_read in [
            (226,5500,41.5,[57.,67.,77.5,87.]), (890,30000,10.5,[40.,44.5,49.5,54.5]),
            (1454,70000,6.5,[35.,38.5,43.,47.5])]:
        rho,cp = 999.1,4183.
        area = plate.width_m*plate.depth_m
        q = re*.001138*area/(rho*plate.diameter_m)
        expected = total_w/(21*rho*cp*q)
        # Water viscosity correlation, SI, temperature in kelvin.
        viscosity = 2.414e-5*10**(247.8/(273.15+15+expected/2-140))
        drop = duct_resistance(plate.length_m,plate.width_m,plate.depth_m,viscosity)*q+.5*rho*(q/area)**2
        x = np.linspace(0,plate.length_m,nx+1)
        field,stats = conjugate(solid,load,ids[0:1],x,np.array([0.,pitch]),plate,np.array([q]),False,k,dz/2,
                                viscosity=viscosity,rho=rho,cp=cp,liquid_k=.61)
        # Probe is 3.175 mm above the heated bottom; our z starts at the grooved wall.
        col = [np.interp(.005637-.003175,(np.arange(nz)+.5)*dz,t) for t in field.reshape(nz,nx).T]
        probes = 15+np.interp(.005+np.arange(4)*.011588,(x[1:]+x[:-1])/2,col)
        mean_flow.append(dict(re=re,flow_lpm=q*21*60000,calculated_drop_pa=drop,figure_drop_pa=dp_read,
                              predicted_outlet_rise_k=stats['outlet_rise_k'],figure_outlet_rise_k=out_read,
                              wall_c=probes.tolist(),figure_wall_c=wall_read,
                              max_abs_probe_error_k=float(np.max(abs(probes-wall_read)))))
    return mean_flow


def preliminary():
    flow = {}
    for reverse,key in enumerate(DIRECTIONS):
        q, rec = hydraulics(PLATE,PUMP_W,reverse)
        assert rec['max_path_residual_pa'] < 1e-5 and rec['max_node_mass_residual_kg_s'] < 1e-11
        assert abs(rec['dissipation_w']-PUMP_W)<1e-9 and abs(rec['hydraulic_w']-PUMP_W)<1e-9
        assert max(rec['max_branch_re'],rec['max_header_re']) < 2300
        # Equal power to each groove, hence each outlet has its own preheating.
        rec['uniform_load_checks'] = {}
        for name,watts in [('Case9',1548.),('Case3',680.)]:
            outlets = watts/len(q)/(RHO*CP*q)
            mixed = np.average(outlets,weights=q)
            rec['uniform_load_checks'][name] = dict(mixed_outlet_rise_k=mixed,
                    branch_range_k=[outlets.min(),outlets.max()],removed_w=float(RHO*CP*(outlets@q)))
        flow[key] = rec
    bench = coupon()
    return dict(layouts_sha256=sha256(LAYOUTS.read_bytes()).hexdigest(),pump_w=PUMP_W,inlet_c=INLET_C,
                geometry=asdict(PLATE),
                network=flow,coupon=bench, empirical_pair_screen_k=2*(1+max(b['max_abs_probe_error_k'] for b in bench)))


def solid_board(p,pose,n):
    data = thermal_case_data(p,pose,100,n)
    width,height = PLATE.length_m*1000,PLATE.count*PLATE.pitch_m*1000
    ox,oy = (200-width)/2,(200-height)/2
    for chip in data['chiplets']:
        chip['placement_mm']['x'] -= ox
        chip['placement_mm']['y'] -= oy
    cfg=data['thermal']
    layers=cfg['layers'][2:-1]  # liquid-cooled interposer roof up to the copper spreader
    for layer in layers:
        rect=layer['rect_mm']
        if layer['id'] in ('interposer','spreader'):
            rect.update(x=0.,y=0.,width=width,height=height)
        else:
            rect['x']-=ox
            rect['y']-=oy
    layers[0]['conductivity_w_mk']=100.  # silicon roof of the extended, grooved interposer
    cfg.update(layers=layers,ambient_c=INLET_C)
    data['package_mm']=dict(width=width,height=height)
    case=parse_case(data,node_limit=500000)
    power,_=rasterize(case)
    solid,load,old_boundary,_,ids,pz=assemble_package(case,power)
    # Replace the reference Robin boundary entirely with the wetted wall.
    return (solid-sparse.diags(old_boundary),load,ids[0],np.array(case.mesh.x_edges_mm)*.001,
            np.array(case.mesh.y_edges_mm)*.001),ids[pz],case


def experiment(source,checks):
    frozen=json.loads(LAYOUTS.read_bytes())
    assert sha256(LAYOUTS.read_bytes()).hexdigest()==checks['layouts_sha256']
    assert (checks['geometry'],checks['pump_w'],checks['inlet_c'])==(asdict(PLATE),PUMP_W,INLET_C)
    result={}
    for name,case_rec in frozen['cases'].items():
        raw=(source/(name+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==case_rec['source_sha256']
        p=Problem.from_imported(json.loads(raw))
        rows={}
        for label,rec in case_rec['poses'].items():
            pose=Layout(np.array(rec['centre_um']),np.array(rec['rotation_deg']))
            admission=inspect(p,pose,np.array(case_rec['reach_mm']),case_rec['cap_m'])
            assert admission['feasible'] and escape_util(p,pose)<=1.
            rows[label]={}
            for resolution in (48,96):
                start=perf_counter()
                args,pz,case=solid_board(p,pose,resolution)
                assembly_s=perf_counter()-start
                scores={}
                for reverse,key in enumerate(DIRECTIONS):
                    start=perf_counter()
                    q=np.array(checks['network'][key]['branch_lpm'])/60000
                    rise,stats=conjugate(*args,PLATE,q,reverse,100.,.00011/2)
                    active=pz>=0
                    peak=np.where(active,rise[np.maximum(pz,0)],-np.inf)
                    iy,ix=np.unravel_index(peak.argmax(),peak.shape)
                    stats.update(peak_c=INLET_C+float(peak[iy,ix]),x_mm=case.mesh.x_centers_mm[ix],
                                 y_mm=case.mesh.y_centers_mm[iy],elapsed_s=perf_counter()-start,
                                 max_roof_c=INLET_C+float(rise[args[2]].max()))
                    expected=checks['network'][key]['uniform_load_checks'][name]['mixed_outlet_rise_k']
                    assert abs(stats['outlet_rise_k']-expected)<1e-5
                    scores[key]=stats
                rows[label][str(resolution)]=dict(assembly_s=assembly_s,directions=scores)
        decision={}
        for key in DIRECTIONS:
            def temperature(label,n): return rows[label][str(n)]['directions'][key]['peak_c']
            delta={n:temperature('A',n)-temperature('B',n) for n in (48,96)}
            mesh=sum(abs(temperature(i,48)-temperature(i,96)) for i in ('A','B'))
            empirical=checks['empirical_pair_screen_k']+mesh
            decision[key]=dict(delta_48_k=delta[48],delta_96_k=delta[96],winner='A' if delta[96]<0 else
                               ('B' if delta[96]>0 else 'tie'),mesh_pair_k=mesh,empirical_plus_mesh_k=empirical,
                               exceeds_mesh=abs(delta[96])>mesh,exceeds_combined=abs(delta[96])>empirical)
        flip=decision['forward']['delta_96_k']*decision['reverse']['delta_96_k']<0
        result[name]=dict(layouts=rows,decision=decision,nominal_flip=bool(flip),
                          combined_resolved_flip=bool(flip and all(d['exceeds_combined'] for d in decision.values())))
        print(name,decision,flush=True)
    return dict(layouts_sha256=checks['layouts_sha256'],cases=result)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['check','evaluate'])
    ap.add_argument('--checks',type=Path,required=True)
    ap.add_argument('--source',type=Path)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    if args.stage=='check':
        write_json(args.checks,preliminary())
    else:
        write_json(args.output,experiment(args.source,json.loads(args.checks.read_bytes())))
