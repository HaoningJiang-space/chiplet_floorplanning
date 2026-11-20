"""Let a small number of measured hotspot sensitivities choose coupled continuous motion."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.geometry import pin_manhattan_um, violations
from chiplet_floorplanning.placement.pin_reach import heat_directed_moves
from chiplet_floorplanning.placement.thermal import AMBIENT_C, thermal_case_data
from compare_continuous_reach import finish, point, verified
from compare_large_pool import write_json
from continuous_reach_geometry import inspect


def isolated_motion(p, report, rec):
    start,best=(report['verified'][i] for i in (0,report['winner']))
    a,b=np.array(start['centre_um']),np.array(best['centre_um'])
    rot=np.array(start['rotation_deg'])
    reach=np.array(rec['reach_mm'])
    out=[]
    for i,name in enumerate(p.names):
        if np.array_equal(a[i],b[i]):
            continue
        xy=a.copy()
        xy[i]=b[i]
        layout=Layout(xy,rot)
        metrics=inspect(p,layout,reach,rec['cap_m'])
        out.append(dict(die=name,delta_mm=((b[i]-a[i])/1000).tolist(),
                        overlaps=violations(p,layout,100)['pairs'],**metrics))
    length=pin_manhattan_um(p,Layout(b,rot))/1000
    report['solo_components']=out
    report['reach_by_class']=[dict(cap_mm=float(limit),signals=int((reach==limit).sum()),
                                   max_mm=float(length[reach==limit].max()))
                              for limit in np.unique(reach)]


def experiment(source, frozen):
    reports={}
    for name,rec in frozen['cases'].items():
        if rec['start'] is None:
            reports[name]=dict(status='no admissible starting layout',new_board_checks=0,responses=0)
            continue
        t=perf_counter()
        raw=(source/(name+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==rec['source_sha256']
        p=Problem.from_imported(json.loads(raw))
        r=rec['start']
        start=Layout(np.array(r['centre_um']),np.array(r['rotation_deg']))
        reach,cap=np.array(rec['reach_mm']),rec['cap_m']
        model,moves=heat_directed_moves(p,start,reach,cap)
        rows=[dict(point(p,start,reach,cap),peak_c=model['start_peak_c'])]
        for fraction,layout,forecast in moves:
            row=point(p,layout,reach,cap)
            assert row['feasible']
            summary,_=verified(p,layout)
            delta=(layout.centre_um-start.centre_um)/1000
            row.update(fraction=fraction,peak_c=summary['peak_power_layer_c'],
                       balance_w=summary['energy_balance_error_w'],
                       predicted_c=forecast,
                       moved_dies=int((abs(delta).max(axis=1)>1e-5).sum()),
                       total_displacement_mm=float(abs(delta).sum()))
            rows.append(row)
        h=thermal_case_data(p,start,100,64)['thermal']['top_h_w_m2k']
        floor=AMBIENT_C+p.power_w.sum()/(h*.2**2)
        result=finish(rows,model['start_peak_c'],rec['geometry_s']+perf_counter()-t,len(rows)-1,
                      len(model['hot_dies']),floor)
        result.update(model,geometry_s=rec['geometry_s'])
        reports[name]=result
        isolated_motion(p,result,rec)
        print(name,[(round(row['peak_c'],5),round(row['wire_m'],4)) for row in rows],flush=True)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','geometry','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--geometry-audit',action='store_true')
    args=parser.parse_args()
    frozen=json.loads(args.geometry.read_bytes())
    if args.geometry_audit:
        data=json.loads(args.output.read_bytes())
        for name,report in data.items():
            if 'verified' in report:
                raw=(args.source/(name+'.json')).read_bytes()
                rec=frozen['cases'][name]
                assert sha256(raw).hexdigest()==rec['source_sha256']
                isolated_motion(Problem.from_imported(json.loads(raw)),report,rec)
        write_json(args.output,data)
    else:
        write_json(args.output,experiment(args.source,frozen))
