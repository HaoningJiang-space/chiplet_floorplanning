"""Compare continuous geometric and thermal decisions with identical pin admission."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.evaluate import Evaluator, thermal_key
from chiplet_floorplanning.placement.methods import Run, relation_space, shortest_seeds
from chiplet_floorplanning.placement.lp import TopologyLP
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from chiplet_floorplanning.placement.search import layout_key
from chiplet_floorplanning.placement.thermal import AMBIENT_C, die_peaks_c, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal_projection import projected_field
from compare_large_pool import write_json
from continuous_reach_geometry import inspect


def verified(p,layout):
    summary,rise,edges=solve(thermal_case_data(p,layout,100,64))
    return summary,die_peaks_c(p,layout,rise,edges)


def point(p,layout,reach,cap):
    return dict(centre_um=layout.centre_um.tolist(),rotation_deg=layout.rotation_deg.tolist(),
                **inspect(p,layout,reach,cap))


class AdmittedRun(Run):
    def __init__(self,evaluator,reach,cap):
        super().__init__(evaluator,3,stall_rounds=2,max_rounds=3)
        self.reach,self.cap=reach,cap
        self.raw,self.rejected=0,0

    def evaluate(self,candidates):
        keep=[]
        for lay in candidates:
            self.raw+=1
            if inspect(self.evaluator.problem,lay,self.reach,self.cap)['feasible']:
                keep.append(lay)
            else:
                self.rejected+=1
        super().evaluate(keep)
        return [self.index.get(layout_key(lay)) for lay in candidates]


def geometry_bank(p,start,reach,cap):
    rng=np.random.default_rng(20261119)
    cell=PinReachCell(p,start,100,reach,cap)
    seeds=shortest_seeds(p,100,[start],None,2.,8,2,int(rng.integers(1<<30)))
    raw=seeds+TopologyLP(p,start,100).sweep(3)
    seen={layout_key(start)}
    candidates=[]

    def add(lay,reason):
        if lay is None or layout_key(lay) in seen:
            return
        if inspect(p,lay,reach,cap)['feasible']:
            seen.add(layout_key(lay))
            candidates.append((lay,reason))

    # Preserve admissible relation-space proposals, then couple infeasible target
    # translations through the pin constraints of the common orientation cell.
    for lay in raw:
        add(lay,'relation_space')
        if len(candidates)<4:
            add(cell.toward(lay.centre_um),'pin-repaired relation target')
        if len(candidates)>=4:
            break
    density=p.power_w/p.size_um.prod(axis=1)
    for i in np.argsort(-density,kind='stable')[:2]:
        for axis,sign in ((0,-1),(0,1),(1,-1),(1,1)):
            target=start.centre_um.copy().astype(float)
            target[i,axis]+=sign*p.carrier_um[axis]/3
            add(cell.toward(target),f'die {i} axis {axis} sign {sign}')
            if len(candidates)==10:
                return candidates
    return candidates


def finish(rows,start_c,cold_s,checks,responses,lower):
    winner=min(range(len(rows)),key=lambda i:(rows[i]['peak_c'],rows[i]['wire_m'],i))
    reverse=min((r for r in rows if r['peak_c']<=start_c+1e-7),key=lambda r:r['wire_m'])
    return dict(verified=rows,winner=winner,peak_c=rows[winner]['peak_c'],wire_m=rows[winner]['wire_m'],
                reverse_m=reverse['wire_m'],new_board_checks=checks,responses=responses,cold_s=cold_s,
                global_lower_c=lower,global_remaining_k=max(0.,rows[winner]['peak_c']-lower))


def compare(args):
    frozen=json.loads(args.geometry.read_bytes())
    out=dict(protocol_sha256=sha256(args.geometry.read_bytes()).hexdigest(),cases={})
    for name,rec in frozen['cases'].items():
        if not rec['start']:
            out['cases'][name]=dict(status='geometrically infeasible' if rec['cycle'] and
               rec['cycle']['rectangle_feasible'] is False else 'no feasible start',new_board_checks=0)
            continue
        clock=perf_counter()
        raw=(args.source/(name+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==rec['source_sha256']
        p=Problem.from_imported(json.loads(raw))
        cap,reach=rec['cap_m'],np.array(rec['reach_mm'])
        st=rec['start']
        start=Layout(np.array(st['centre_um']),np.array(st['rotation_deg']))
        base=point(p,start,reach,cap)
        assert base['feasible']
        summary,die=verified(p,start)
        base.update(peak_c=summary['peak_power_layer_c'],balance_w=summary['energy_balance_error_w'])
        start_c=base['peak_c']
        shared_s=perf_counter()-clock
        # All input heat leaves the uniform 200 x 200 mm top. The highest
        # source-layer temperature exceeds the area-averaged surface temperature.
        h=thermal_case_data(p,start,100,64)['thermal']['top_h_w_m2k']
        global_lower=AMBIENT_C+p.power_w.sum()/(h*.2**2)
        case=dict(start=base,start_s=shared_s,geometry_s=rec['geometry_s'],arms={})
        common=shared_s+rec['geometry_s']
        clock=perf_counter()
        ev=Evaluator(p,100,resolution=64)
        ev.cache[thermal_key(p,start)]=np.r_[start_c,die]
        ev.solves=1
        run=AdmittedRun(ev,reach,cap)
        relation_space(run,[start],np.random.default_rng(20261119),milp_s=2.,anneal_steps=8,
                       chains=2,batch=6,levels=3,lp_share=1.,caps=0)
        rows=[dict(point(p,lay,reach,cap),peak_c=t) for lay,t in zip(run.layouts,run.peaks)]
        assert ev.solves<=3 and len(ev.cache)==ev.solves and all(r['feasible'] for r in rows)
        baseline=finish(rows,start_c,common+perf_counter()-clock,ev.solves-1,0,global_lower)
        baseline.update(raw=run.raw,rejected=run.rejected)
        case['arms']['relation_space']=baseline
        clock=perf_counter()
        bank=geometry_bank(p,start,reach,cap)
        bank_rows=[dict(point(p,lay,reach,cap),origin=reason,
                        moved_dies=int(np.any(abs(lay.centre_um-start.centre_um)>1e-5,axis=1).sum()))
                   for lay,reason in bank]
        generation_s=perf_counter()-clock
        case.update(bank=bank_rows,generation_s=generation_s)
        for mode in ('reach','thermal'):
            clock=perf_counter()
            scores=[]
            for i,(lay,_) in enumerate(bank):
                score=projected_field(p,lay)[0] if mode=='thermal' else {}
                scores.append(score)
            order=sorted(range(len(bank)),key=lambda i:(scores[i].get('estimated_peak_c',0.),
                                                        bank_rows[i]['wire_m'],i))
            rows=[base]
            for i in order[:2]:
                summary,_=verified(p,bank[i][0])
                pk=summary['peak_power_layer_c']
                if scores[i]:
                    assert scores[i]['lower_peak_c']<=pk+1e-6
                rows.append(dict(bank_rows[i],bank_id=i,peak_c=pk,balance_w=summary['energy_balance_error_w']))
            arm=finish(rows,start_c,common+generation_s+perf_counter()-clock,len(rows)-1,
                       len(bank) if mode=='thermal' else 0,global_lower)
            exact={r['bank_id']:r['peak_c'] for r in rows[1:]}
            lower=min([start_c]+[exact.get(i,max(global_lower,s.get('lower_peak_c',global_lower)))
                                 for i,s in enumerate(scores)])
            arm.update(bank_remaining_k=max(0.,arm['peak_c']-lower),scores=scores)
            case['arms'][mode]=arm
        out['cases'][name]=case
        write_json(args.output,out)
        print(name,len(bank),[(m,round(v['peak_c'],4),v['new_board_checks']) for m,v in case['arms'].items()],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('geometry','source','output'):
        ap.add_argument('--'+name,type=Path,required=True)
    compare(ap.parse_args())
