"""Search corner arrangements of the four hot CPUs on the original Case3 carrier."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.special import k0

from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um, solve, thermal_case_data
from chiplet_floorplanning.placement.geometry import rotate
from compare_wire_heat import digest
from wire_heat_bound import thermal_modes


class BundleLengths:
    def __init__(self, problem):
        pins = {}
        for (a,b),(oa,ob) in zip(problem.pin_chip,problem.pin_offset_um):
            if a>b:
                a,b,oa,ob = b,a,ob,oa
            pins.setdefault((a,b),[]).append((oa,ob))
        self.data = {}
        self.ring = [(a,b) for a,b in pins if b<4]
        assert set(self.ring)=={(0,1),(0,2),(1,3),(2,3)}
        assert set(pins)-set(self.ring)=={(i,i+4) for i in range(4)}
        for (a,b),v in pins.items():
            va,vb = np.array(v).transpose(1,0,2)
            for ra,rb in product(range(4),repeat=2):
                offset = np.sort(rotate(va,90*ra)-rotate(vb,90*rb),axis=0)
                self.data[a,b,ra,rb] = [(axis,np.r_[0,np.cumsum(axis)]) for axis in offset.T]

    @lru_cache(maxsize=None)
    def length(self,a,b,ra,rb,dx,dy):
        wire = 0.
        for (axis,prefix),d in zip(self.data[a,b,ra,rb],(dx,dy)):
            n = len(axis)
            i = int(axis.searchsorted(d))
            wire += (2*i-n)*d+prefix[-1]-2*prefix[i]
        return wire

    def best(self,centres,parity):
        tables={}
        for a,b in self.ring+[(i,i+4) for i in range(4)]:
            dx,dy=centres[b]-centres[a]
            tables[a,b] = np.array([[self.length(a,b,int(parity[a]+2*i),
                                     int(parity[b]+2*j) if b<4 else j,dx,dy)
                                     for j in range(2 if b<4 else 4)] for i in range(2)])
        best=np.inf
        for flips in product((0,1),repeat=4):
            cost=sum(tables[a,b][flips[a],flips[b]] for a,b in self.ring)
            turns=[int(parity[i]+2*flips[i]) for i in range(4)]
            for i in range(4):
                row=tables[i,i+4][flips[i]]
                turns.append(int(row.argmin()))
                cost+=row.min()
            if cost<best:
                best,rotation=cost,np.array(turns)*90
        return best/1e6, Layout(centres,rotation)


def thermal_key(centres,size,power,carrier):
    relative=centres-carrier/2
    variants=[]
    for swap in (False,True):
        c=relative[:,::-1] if swap else relative
        footprint=size[:,::-1] if swap else size
        for signs in product((-1,1),repeat=2):
            variants.append(tuple(sorted(map(tuple,np.column_stack((c*signs,footprint,power))))))
    return min(variants)


def candidates(p,gap,cert,cap):
    carrier=np.asarray(p.carrier_um)
    assert carrier[0]==carrier[1] and p.count==8
    signs=np.array([[-1,-1],[1,-1],[-1,1],[1,1]])
    costs=BundleLengths(p)
    sigma2=(p.size_um**2).sum(axis=1)/12e6
    radii,weight=thermal_modes(cert)
    self_k=np.array([d['self_floor_k'] for d in cert['dies']])
    feasible={}
    counts=dict(proposals=0,legal=0,in_cap=0)
    for parity in ((0,0,0,0),(1,1,1,1),(0,1,1,0),(1,0,0,1)):
        sizes=p.size_um.copy()
        for i in range(4):
            if parity[i]: sizes[i]=sizes[i,::-1]
        for inset in product((0,1000,2000,4000),repeat=2):
            cpus=carrier/2+signs*(carrier/2-sizes[:4]/2-inset)
            for axes,extra in product(product((0,1),repeat=4),(0,2000,4000)):
                ram=cpus.copy()
                for i,axis in enumerate(axes):
                    ram[i,axis]-=signs[i,axis]*((sizes[i,axis]+sizes[i+4,axis])/2+gap+extra)
                ram=np.clip(ram,sizes[4:]/2,carrier-sizes[4:]/2)
                centres=np.concatenate((cpus,ram))
                layout=Layout(centres,np.array([*parity,0,0,0,0])*90)
                counts['proposals']+=1
                if not is_legal(p,layout,gap): continue
                counts['legal']+=1
                length,layout=costs.best(centres,parity)
                if length>cap+1e-9: continue
                counts['in_cap']+=1
                key=thermal_key(centres,sizes,p.power_w,carrier)
                if key in feasible and feasible[key][1]<=length: continue
                distance2=np.sum((centres[:,None]-centres[None,:])**2,axis=2)/1e6
                rms=np.sqrt(distance2+sigma2[:,None]+sigma2[None,:])
                kernel=k0(rms[:,:,None]/radii)@weight
                np.fill_diagonal(kernel,0)
                score=float((self_k+kernel@p.power_w).max())
                feasible[key]=(score,length,layout)
    counts['distinct_thermal_geometries']=len(feasible)
    return sorted(feasible.values(),key=lambda row:(row[0],row[1]))[:48],counts


def measure(job):
    p,gap,layout,grid=job
    stats,_,_=solve(thermal_case_data(p,layout,gap,grid))
    return dict(peak_c=stats['peak_power_layer_c'],error_w=stats['energy_balance_error_w'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=12)
    args=parser.parse_args()
    source=args.data/'physical-calibration/atplace-import-v1/Case3.json'
    evidence=Path(__file__).resolve().parents[1]/'docs/evidence'
    prior=next(c for c in json.loads((evidence/'global-heat-floor-v1.json').read_text())['cases']
               if c['certificate']['case']=='Case3')
    ref=next(r for r in json.loads((evidence/'headroom-selection-v1.json').read_text())['records'] if r['case']=='Case3')
    assert digest(source)==ref['case_sha256']==prior['certificate']['case_sha256']
    p=Problem.from_imported(json.loads(source.read_text()))
    gap=ref['gap_um']
    cap=prior['budgets']['span']['cap_m']
    trials,counts=candidates(p,gap,prior['certificate'],cap)
    points=[]
    with ProcessPoolExecutor(args.workers) as pool:
        for grid in (64,96):
            measured=pool.map(measure,[(p,gap,l,grid) for _,_,l in trials])
            for i,((pred,wire,l),obs) in enumerate(zip(trials,measured)):
                actual=float(pin_manhattan_um(p,l).sum()/1e6)
                assert abs(wire-actual)<1e-8 and actual<=cap+1e-9 and is_legal(p,l,gap)
                if grid==64:
                    points.append(dict(centre_um=l.centre_um.tolist(),rotation_deg=l.rotation_deg.tolist(),
                                       length_m=actual,heuristic_rise_k=pred,checks={}))
                points[i]['checks'][grid]=obs
        chosen=sorted(range(len(points)),key=lambda i:max(v['peak_c'] for v in points[i]['checks'].values()))[:4]
        for i,obs in zip(chosen,pool.map(measure,[(p,gap,trials[i][2],128) for i in chosen])):
            points[i]['checks'][128]=obs
    result=dict(case='Case3',case_sha256=digest(source),driver_sha256=digest(Path(__file__)),counts=counts,
                cap_m=cap,points=points,fine_ids=chosen)
    args.output.write_text(json.dumps(result,allow_nan=False)+'\n')
    print(counts, len(points),chosen,flush=True)


if __name__=='__main__':
    main()
