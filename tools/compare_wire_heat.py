"""Compare wire-conditioned thermal floors with real feasible layouts at the same power."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um, solve, thermal_case_data
from global_heat_floor import floor_for_case
from wire_heat_bound import DistanceRelaxation


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def square_control():
    names=('SW','SE','NW','NE')
    pins,offsets=[],[]
    for i,j,axis in [(0,1,0),(2,3,0),(0,2,1),(1,3,1)]:
        for t in np.linspace(-3500,3500,128):
            a,b=np.array([t,t]),np.array([t,t])
            a[axis],b[axis]=4000,-4000
            pins.append((i,j))
            offsets.append((a,b))
    p=Problem('square_wire_control',names,np.full((4,2),8000.),np.full(4,60.),
              (96000.,96000.),np.array(pins),np.array(offsets))
    signs=np.array([[-1,-1],[1,-1],[-1,1],[1,1]])
    layouts={pitch:Layout(48000+signs*pitch*500,np.zeros(4,dtype=int)) for pitch in (8.5,10,14,20,30,44,60)}
    return p,layouts


def check_layout(p,lp,layout,gap_um):
    assert is_legal(p,layout,gap_um)
    lengths=pin_manhattan_um(p,layout)/1000
    d=np.linalg.norm(layout.centre_um[lp.a]-layout.centre_um[lp.b],axis=1)/1000
    from scipy.special import k0
    sizes=p.size_um/1000
    sigma2=(sizes*sizes).sum(axis=1)/12
    lo=np.sqrt(lp.dmin**2+sigma2[lp.a]+sigma2[lp.b])
    hi=np.sqrt(lp.dmax**2+sigma2[lp.a]+sigma2[lp.b])
    chord=lo+(hi-lo)*(d-lp.dmin)/(lp.dmax-lp.dmin)
    y=k0(chord[:,None]/np.array(lp.modes['radii_mm']))@np.array(lp.modes['coeff_k_w'])
    ids=np.sort(p.pin_chip,axis=1)
    bundle=[lengths[(ids[:,0]==e['a'])&(ids[:,1]==e['b'])].mean() for e in lp.edges]
    point=np.r_[d,y,bundle]
    assert max((lp.base_matrix@point-lp.base_rhs).max(),(lp.lo-point).max(),(point-lp.hi).max()) < 1e-6
    assert abs(lp.budget_row@point+lp.internal_mm-lengths.sum()) < 1e-6
    return float(lengths.sum()/1000)


def compute(p,cert,gap_um,layouts,observed,caps):
    relaxation=DistanceRelaxation(p,cert,gap_um/1000)
    points=[]
    for idx,layout in layouts.items():
        length=check_layout(p,relaxation,layout,gap_um)
        if observed is None:
            peaks,balances={},{}
            for grid in (64,96,128):
                stats,_,_=solve(thermal_case_data(p,layout,gap_um,grid))
                peaks[grid]=stats['peak_power_layer_c']
                balances[grid]=stats['energy_balance_error_w']
            points.append(dict(id=idx,length_m=length,peak_c=peaks,energy_balance_error_w=balances))
            assert abs(length-512*(idx-8)/1000)<1e-9
        else:
            base=observed[idx]
            assert abs(base['length_m']-length)<1e-9
            peaks={int(grid):v['1']['peak_c'] for grid,v in base['observations'].items()}
            points.append(dict(id=idx,length_m=length,peak_c=peaks))
    if caps is None:
        caps={str(row['id']):row['length_m'] for row in points}
    bounds={'unlimited':relaxation.lower(None)}
    for label,cap in sorted(caps.items(),key=lambda item:-item[1]):
        result=relaxation.lower(cap)
        # A valid bound for a looser upper limit also applies to every tighter limit.
        result['floor_c']=max(result['floor_c'],max(b['floor_c'] for b in bounds.values()))
        eligible=[r for r in points if r['length_m']<=cap+1e-9]
        witness=min(eligible,key=lambda r:max(r['peak_c'].values()))
        result['witness_id']=witness['id']
        result['witness_peak_c']=max(witness['peak_c'].values())
        assert all(min(r['peak_c'].values())>=result['floor_c']-1e-6 for r in eligible)
        bounds[label]=result
    return dict(case=p.name,names=p.names,prior_floor_c=cert['floor_c'],modes=relaxation.modes,
                wire_bundle_minimum_sum_m=sum(e['n']*e['min_mm'] for e in relaxation.edges)/1000,
                internal_m=relaxation.internal_mm/1000,edges=relaxation.edges,points=points,bounds=bounds)


def archive_case(data,ref,prior):
    cert=prior['certificate']
    name=cert['case']
    if name.startswith('Case'):
        source=data/'physical-calibration/atplace-import-v1'/(name+'.json')
        run=data/'rs-grb-v4'/name.lower()
    else:
        source=data/'industrial-v1/cases'/(name+'.json')
        run=data/'industrial-v1/runs'/name
    assert digest(source)==cert['case_sha256'] and digest(run/'summary.json')==cert['summary_sha256']
    p=Problem.from_imported(json.loads(source.read_text()))
    points={r['archive_id']:r for r in prior['legal_layouts']}
    with np.load(run/'layouts.npz') as z:
        layouts={i:Layout(z['centre_um'][i],z['rotation_deg'][i]) for i in points}
    caps={k:item['cap_m'] for k,item in prior['budgets'].items()}
    out=compute(p,cert,ref['gap_um'],layouts,points,caps)
    return dict(out,case=name,case_sha256=cert['case_sha256'],archive_sha256=cert['summary_sha256'])


def control():
    p,layouts=square_control()
    cert=floor_for_case(p,thermal_case_data(p,layouts[8.5],500,64))
    return dict(compute(p,cert,500,layouts,None,None),certificate=cert)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    evidence=Path(__file__).resolve().parents[1]/'docs/evidence'
    refs={r['case']:r for r in json.loads((evidence/'headroom-selection-v1.json').read_text())['records']}
    prior_file=evidence/'global-heat-floor-v1.json'
    digests={k:digest(Path(__file__).with_name(k)) for k in ('compare_wire_heat.py','wire_heat_bound.py','global_heat_floor.py')}
    with ProcessPoolExecutor(args.workers) as pool:
        jobs=[pool.submit(control)]
        for prior in json.loads(prior_file.read_text())['cases']:
            jobs.append(pool.submit(archive_case,args.data,refs[prior['certificate']['case']],prior))
        for job in as_completed(jobs):
            row=job.result()
            row.update(script_sha256=digests,prior_sha256=digest(prior_file))
            (args.output/(row['case']+'.json')).write_text(json.dumps(row,allow_nan=False)+'\n')
            print(row['case'],[(k,round(b['floor_c'],2)) for k,b in row['bounds'].items()],flush=True)


if __name__=='__main__':
    main()
