"""Bound remaining cooling in the full 3D package over all equal-footprint permutations."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import linear_sum_assignment
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package, checked_solution, require_heat_path
from chiplet_floorplanning.placement.geometry import is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.slot_margin import choose_hot_slots
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from chiplet_floorplanning.power import rasterize
from import_margin_holdouts import REV, SEED


class SlotPackage:
    def __init__(self, p, start):
        case = parse_case(thermal_case_data(p,start,100,64),node_limit=450000)
        watts, records = rasterize(case)
        a, b, self.sink, _, layers, z = assemble_package(case,watts)
        require_heat_path(a,self.sink)
        self.a = a
        self.factor = splu(a.tocsc(),permc_spec="MMD_AT_PLUS_A")
        self.layer = layers[z]
        self.active = self.layer[self.layer>=0]
        self.slots = []
        x,y = np.asarray(case.mesh.x_edges_mm),np.asarray(case.mesh.y_edges_mm)
        rr,cc,ww = [],[],[]
        by_name = {r["chiplet"]:r["package_rect_mm"] for r in records}
        for i,name in enumerate(p.names):
            rect=by_name[name]
            # Snapping to the FV geometry lines uses this model's conformal mesh.
            ix = [int(abs(x-v).argmin()) for v in (rect["x"],rect["x"]+rect["width"])]
            iy = [int(abs(y-v).argmin()) for v in (rect["y"],rect["y"]+rect["height"])]
            cells = self.layer[iy[0]:iy[1],ix[0]:ix[1]].ravel()
            area = np.outer(np.diff(y)[iy[0]:iy[1]],np.diff(x)[ix[0]:ix[1]]).ravel()
            assert len(cells) and np.all(cells>=0)
            rr.extend(cells)
            cc.extend([i]*len(cells))
            ww.extend(area/area.sum())
            self.slots.append(cells)
        self.deposit = coo_matrix((ww,(rr,cc)),shape=(a.shape[0],p.count)).tocsr()
        np.testing.assert_allclose(self.deposit@p.power_w,b,rtol=1e-10,atol=1e-10)
        self.rows = {}

    def temperatures(self, powers):
        rhs = self.deposit@powers
        rise = self.factor.solve(rhs)
        checked_solution(self.a,rhs,self.sink,rise)
        return rise

    def observe(self,node):
        node=int(node)
        if node not in self.rows:
            impulse=np.zeros(self.a.shape[0])
            impulse[node]=1.
            response=self.factor.solve(impulse,trans="T")
            self.rows[node]=self.deposit.T@response


def problem(rows,cols,topology,upstream,uniform,grid_start=False):
    name=f"slots_{rows}x{cols}_{topology}"
    chip=json.loads((upstream/"inputs/chiplets/chiplets_example_experiment.json").read_bytes())["example_experiment"]
    size=1000*np.array([chip["dimensions"][k] for k in "xy"])
    offsets=1000*np.array([[phy["x"],phy["y"]] for phy in chip["phys"]])-size/2
    sys.path.insert(0,str(upstream))
    spec=importlib.util.spec_from_file_location("rapid_topology_scale",upstream/"generate_topology.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    edges=getattr(module,"generate_"+topology+"_topology")(dict(rows=rows,cols=cols))
    pins=[[e[k] for k in ("ep1","ep2")] for e in edges]
    xy=np.array([[j,i] for i in range(rows) for j in range(cols)])*(size+3000)+size/2+3000
    n=rows*cols
    watts=np.full(n,chip["power"]*.1) if uniform else np.repeat([chip["power"]*.05,chip["power"]*.15],n//2)
    p=Problem(name,tuple(f"die_{k}" for k in range(n)),np.tile(size,(n,1)),watts,
              tuple(np.array([cols-1,rows-1])*(size+3000)+size+6000),
              np.array([[s["outer_id"] for s in pair] for pair in pins],int),
              np.array([[offsets[s["inner_id"]] for s in pair] for pair in pins]))
    initial_xy=xy if grid_start else xy[np.random.default_rng(SEED).permutation(n)]
    return p, Layout(initial_xy,np.zeros(n,int))


def realize(p,start,hot):
    """Assign physical identities within each thermal class and improve pin cost."""
    n=p.count
    high=p.power_w==p.power_w.max()
    selected=np.zeros(n,bool)
    selected[hot]=True
    xy=start.centre_um
    distance=abs(xy[:,None,:]-xy[None,:,:]).sum(axis=2)
    assign=np.empty(n,int)
    for flag in (False,True):
        dies=np.flatnonzero(high==flag)
        sites=np.flatnonzero(selected==flag)
        i,j=linear_sum_assignment(distance[np.ix_(dies,sites)])
        assign[dies[i]]=sites[j]
    i,j=p.pin_chip.T
    offsets=p.pin_offset_um[:,0]-p.pin_offset_um[:,1]  # all rotations here are zero
    def costs(perms):
        v=xy[perms[:,i]]-xy[perms[:,j]]+offsets
        return abs(v).sum(axis=(1,2))/1e6
    left,right=np.triu_indices(n,1)
    keep=high[left]==high[right]
    left,right=left[keep],right[keep]
    cost=float(costs(assign[None,:])[0])
    for _ in range(n):
        trials=np.tile(assign,(len(left),1))
        idx=np.arange(len(left))
        trials[idx,left],trials[idx,right]=assign[right],assign[left]
        wire=costs(trials)
        k=int(wire.argmin())
        if wire[k]>=cost-1e-12:
            break
        assign=trials[k].copy()
        cost=float(wire[k])
    exact=pin_manhattan_um(p,Layout(xy[assign],start.rotation_deg)).sum()/1e6
    assert abs(exact-cost)<1e-9
    return assign, cost


def score(p,start,uniform):
    before=perf_counter()
    package=SlotPackage(p,start)
    initial=package.temperatures(p.power_w)
    nodes=package.active
    old=float(initial[nodes].max())
    cap=float(pin_manhattan_um(p,start).sum()/1e6)
    low,high=float(p.power_w.min()),float(p.power_w.max())
    count=int((p.power_w==high).sum())
    best=old
    best_perm=np.arange(p.count)
    best_cost=cap
    trace=[]
    masters=[]
    reciprocity_error=0.
    start_nodes=[int(c[initial[c].argmax()]) for c in package.slots]
    for node in sorted(set(start_nodes)|{int(nodes[initial[nodes].argmax()])}) if not uniform else []:
        package.observe(node)
    setup=perf_counter()-before
    best_lower=old if uniform else 0.
    for _ in range(0 if uniform else 4):
        matrix=np.array(list(package.rows.values()))
        hot,bounds=choose_hot_slots(matrix,low,high,count)
        masters.append(dict(observers=len(matrix), **bounds))
        best_lower=max(best_lower,bounds["lower_k"])
        assert best_lower<=best+1e-6
        if best-best_lower<=1e-6:
            break
        assign,cost=realize(p,start,hot)
        powers=np.full(p.count,low)
        powers[hot]=high
        np.testing.assert_array_equal(powers[assign],p.power_w)
        final=package.temperatures(powers)
        error=float(np.max(np.abs(matrix@powers-final[np.array(list(package.rows),dtype=int)])))
        reciprocity_error=max(reciprocity_error,error)
        assert error<1e-7
        cell=int(nodes[final[nodes].argmax()])
        peak=float(final[cell])
        allowed=bool(cost<=cap+1e-9)
        if allowed and (peak,cost)<(best,best_cost):
            best,best_cost,best_perm=peak,cost,assign.copy()
        novel=cell not in package.rows
        trace.append(dict(bounds=bounds,hot_slots=hot.tolist(),chip_to_slot=assign.tolist(),wire_m=cost,
            feasible=allowed,peak_c=AMBIENT_C+peak,peak_lower_c=AMBIENT_C+best_lower,
            attainable_c=AMBIENT_C+best,gap_k=max(0.,best-best_lower),new_hotspot=novel))
        if not novel:
            break
        package.observe(cell)
    if masters and masters[-1]["observers"] < len(package.rows):
        # Charge the final re-bound after the last board check; it issues no new layout.
        _,bounds=choose_hot_slots(np.array(list(package.rows.values())),low,high,count)
        masters.append(dict(observers=len(package.rows), **bounds))
        best_lower=max(best_lower,bounds["lower_k"])
    decision_time=perf_counter()-before
    chosen=Layout(start.centre_um[best_perm],start.rotation_deg)
    assert is_legal(p,chosen,100)
    raw=solve(thermal_case_data(p,chosen,100,64),node_limit=450000)[0]
    assert abs(raw["peak_power_layer_c"]-(best+AMBIENT_C))<1e-6 and best_lower<=best+1e-6
    including_audit=perf_counter()-before
    responses=np.asarray(list(package.rows.values()),dtype="<f8")
    return dict(count=p.count, uniform=uniform, cap_m=cap, start_um=start.centre_um.tolist(),
                wire_m=best_cost, selected=best_perm.tolist(), peak_start_c=AMBIENT_C+old,
                peak_selected_c=raw["peak_power_layer_c"], gain_k=old-best,
                max_possible_gain_k=max(0.,old-best_lower), remaining_k=max(0.,best-best_lower),
                within_0p1_k=bool(best-best_lower<=.1), trace=trace,masters=masters,adjoints=len(package.rows),
                fv_nodes=package.a.shape[0],power_layer_cells=len(nodes),
                observer_nodes=list(package.rows),response_sha256=hashlib.sha256(responses.tobytes()).hexdigest(),
                setup_s=setup,search_s=decision_time,with_independent_audit_s=including_audit,
                audit_balance_w=raw["energy_balance_error_w"],reciprocity_error_k=reciprocity_error,
                independent_3d_checks=1)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upstream",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--grid-start",action="store_true",help="Tight-wire controls from the original topology order")
    args=ap.parse_args()
    up=args.upstream.resolve()
    assert subprocess.check_output(["git","-C",str(up),"rev-parse","HEAD"],text=True).strip()==REV
    results=dict(seed=SEED,rapidchiplet=REV,weights_w=[1.025,3.075],numpy=np.__version__,
                 scipy=scipy.__version__,cases={})
    cases=((4,6,"mesh",False),(8,8,"folded_torus",False)) if args.grid_start else (
        (4,6,"mesh",False),(6,6,"folded_torus",False),(6,8,"mesh",False),
        (8,8,"folded_torus",False),(4,6,"mesh",True))
    for rows,cols,top,uniform in cases:
        then=perf_counter()
        p,start=problem(rows,cols,top,up,uniform,args.grid_start)
        row=score(p,start,uniform)
        row["including_input_s"]=perf_counter()-then
        name=p.name+("_uniform" if uniform else "")+("_grid_start" if args.grid_start else "")
        results["cases"][name]=row
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(results,indent=2,allow_nan=False)+"\n",encoding="utf8",newline="\n")
        print(name,len(row["trace"]),round(row["gain_k"],4),round(row["remaining_k"],4),flush=True)


if __name__=="__main__":
    main()
