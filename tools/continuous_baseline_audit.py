"""Audit the historical full stage mix and local track escape at continuous endpoints."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, Problem
from chiplet_floorplanning.placement.evaluate import thermal_key
from chiplet_floorplanning.placement.geometry import pin_points_um
from chiplet_floorplanning.placement.methods import Run, relation_space
from compare_continuous_reach import finish, point, verified
from compare_large_pool import write_json


class CountDirect(Run):
    direct = 0

    def evaluate(self, candidates):
        before = self.evaluator.solves
        result = super().evaluate(candidates)
        self.direct += self.evaluator.solves-before
        return result


def escape_util(p,lay):
    side=np.array(p.carrier_um)/1000
    shape=np.ceil(side).astype(int)
    bins=np.clip(np.floor(pin_points_um(p,lay)/1000).astype(int),0,shape-1)
    index=bins[:,:,0]+shape[0]*bins[:,:,1]
    cross=index[index[:,0]!=index[:,1]].ravel()
    demand=np.bincount(cross,minlength=int(np.prod(shape))).reshape(shape[::-1])
    x,y=np.arange(shape[0]),np.arange(shape[1])
    width,height=np.minimum(1.,side[0]-x),np.minimum(1.,side[1]-y)
    sides_x=(x>0).astype(int)+(x+1<shape[0])
    sides_y=(y>0).astype(int)+(y+1<shape[1])
    cap=(height*500).astype(int)[:,None]*sides_x[None,:]+sides_y[:,None]*(width*500).astype(int)[None,:]
    return float((demand/cap).max())


def audit(source,freeze,previous,directed):
    results={}
    for name,rec in freeze['cases'].items():
        if not rec['start']:
            continue
        then=perf_counter()
        raw=(source/(name+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==rec['source_sha256']
        p=Problem.from_imported(json.loads(raw))
        def pose(v):
            return Layout(np.array(v['centre_um']),np.array(v['rotation_deg']))
        start=pose(rec['start'])
        cap,reach=rec['cap_m'],np.array(rec['reach_mm'])
        summary,die=verified(p,start)
        pk=summary['peak_power_layer_c']
        ev=Evaluator(p,100,resolution=64)
        ev.cache[thermal_key(p,start)]=np.r_[pk,die]
        ev.solves=1
        run=CountDirect(ev,3,stall_rounds=2,max_rounds=3)
        relation_space(run,[start],np.random.default_rng(20261119),milp_s=2.,anneal_steps=8,
                       chains=2,batch=6,levels=3)
        rows=[dict(point(p,l,reach,cap),peak_c=t) for l,t in zip(run.layouts,run.peaks)]
        accepted=[r for r in rows if r['feasible']]
        assert ev.solves<=3
        case=previous['cases'][name]
        floor=case['arms']['thermal']['global_lower_c']
        report=finish(accepted,pk,rec['geometry_s']+perf_counter()-then,ev.solves-1,0,floor)
        report.update(proposed=rows,stop_reason=run.stop_reason)
        # Frozen two-check runs here exhausted the short-end FV budget. If an
        # SLP job executed, its adjoints need a separate budget accounting.
        if run.direct!=ev.solves-1 or ev.solves!=len(ev.cache):
            raise ValueError('inspect native SLP work before reporting its response count')
        esc={}
        for mode,arm in dict(case['arms'],hot_move=directed[name],native_relation=report).items():
            esc[mode]=[escape_util(p,pose(r)) for r in arm['verified']]
        results[name]=dict(native_relation=report,escape_by_verified=esc)
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','geometry','previous','directed','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    read=lambda path: json.loads(path.read_bytes())
    write_json(args.output,audit(args.source,read(args.geometry),read(args.previous),read(args.directed)))
