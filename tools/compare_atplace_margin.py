"""Matched wire cap and independent 3D evaluation of ATPlace and signed-margin placements."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.geometry import rotate
from chiplet_floorplanning.placement.common_move import HotspotResponse
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.footprint_response import FootprintResponse
from chiplet_floorplanning.placement.joint_generation import JointLandings
from chiplet_floorplanning.placement.joint_margin import PairMargin
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from evidence_io import write_pretty_json as write
from direct_relocation import physical_cost
from solve_joint_margin import starting_cells
from transfer_placement import starting_cases


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df"
NAMES = ("Case1", "Case4", "Case5")


def problem_at(out):
    case = json.loads((out/"input.json").read_bytes())
    raw = (out/"source.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == case["source_sha256"]
    p = Problem.from_imported(json.loads(raw))
    return case, p, Layout(np.array(case["start_um"]),np.array(case["angles"]))


def field(p, layout):
    return solve(thermal_case_data(p,layout,100,64), node_limit=450000)


def labels(out):
    _, p, _ = problem_at(out)
    saved = np.load(out/"sampled.npz")
    names = saved["names"].tolist()
    order = [names.index(n) for n in p.names]
    nx, ny = saved["grid"]
    width, height = np.asarray(p.carrier_um)/1000
    ox, oy = (200-np.asarray(p.carrier_um)/1000)/2
    x = ox+(np.arange(nx)+.5)*width/nx
    y = oy+(np.arange(ny)+.5)*height/ny
    results = []
    for geometry in saved["geometry"]:
        g = geometry[order]
        angles = np.where(np.isclose(g[:,2],p.size_um[:,0]),0,90)
        np.testing.assert_allclose(np.where(angles[:,None]==0,p.size_um,p.size_um[:,::-1]),g[:,2:])
        _, rise, (ex,ey) = field(p,Layout(g[:,:2].astype(float),angles))
        # FV unknowns are cell averages. ATPlace targets are XY grid-centre samples.
        results.append(rise[np.ix_(np.searchsorted(ey,y,side="right")-1,
                                  np.searchsorted(ex,x,side="right")-1)].T)
    assert np.isfinite(results).all()
    np.save(out/"labels.npy", results)


def candidate(p, layout, cap):
    cost = physical_cost(p,layout,None)
    legal = is_legal(p,layout,100)
    feasible = bool(legal and cost <= cap+1e-9)
    peak = field(p,layout)[0]["peak_power_layer_c"] if feasible else None
    return dict(wire_m=cost, legal=legal, feasible=feasible, peak_c=peak,
                centre_um=layout.centre_um.tolist(), rotation_deg=layout.rotation_deg.tolist())


def margin_candidates(p, start, cap):
    domain = JointLandings(p,p,start,None,cap)
    sheet = CooledSheet(p,np.array([100.,100.]))
    initial = sheet.temperatures(sheet.power_map(start))
    seen, excluded = set(), set()
    projection = None
    def observe(cell):
        nonlocal projection
        if cell in seen:
            return
        row = HotspotResponse.at_cell(sheet,initial,cell)
        if projection is None:
            projection = FootprintResponse(domain,row)
        domain.headroom.append(row.headroom_k)
        domain.cooling.append(projection.cooling(row))
        seen.add(cell)
    for cell in starting_cells(p,sheet,initial,True,True):
        observe(cell)
    solver = PairMargin(domain)
    for _ in range(4):
        proposal = solver.propose(excluded)
        if proposal is None:
            break
        key, move, _ = proposal
        excluded.add(key)
        layout = move.apply(start)
        final = sheet.temperatures(sheet.power_map(layout))
        observe(tuple(map(int,np.unravel_index(final.argmax(),final.shape))))
        yield layout


def assess(out, arm):
    case,p,start = problem_at(out)
    cap = case["cap_m"]
    records = [candidate(p,start,cap)]
    if arm == "margin":
        records.extend(candidate(p,layout,cap) for layout in margin_candidates(p,start,cap))
    else:
        export = json.loads((out/(arm+".json")).read_bytes())
        dies = {c["name"]:c for c in export["chiplets"]}
        xy = np.array([[dies[n]["x"],dies[n]["y"]] for n in p.names])
        angles = np.array([int(round(dies[n]["angle_rad"]/(np.pi/2)))*90%360 for n in p.names])
        row = candidate(p,Layout(xy,angles),cap)
        row["author_wire_m"] = export["source_wire_m"]
        # The upstream reporting loop adds thousands of net lengths sequentially
        # in float32. Replay that arithmetic; the common cap still uses float64.
        offsets = rotate(p.pin_offset_um.astype(np.float32),angles[p.pin_chip])
        endpoints = xy.astype(np.float32)[p.pin_chip] + offsets
        net_um = np.abs(endpoints[:,0]-endpoints[:,1]).sum(axis=1,dtype=np.float32)
        replay_um = float(np.cumsum(net_um,dtype=np.float32)[-1])
        author_um = row["author_wire_m"]*1e6
        np.testing.assert_allclose(replay_um, author_um, rtol=0, atol=2*np.spacing(np.float32(author_um)))
        row["replayed_author_wire_m"] = replay_um / 1e6
        records.append(row)
    valid = [r for r in records if r["feasible"]]
    best = min(valid,key=lambda r:(r["peak_c"],r["wire_m"]))
    reverse = min(r["wire_m"] for r in valid if r["peak_c"] <= records[0]["peak_c"] + 1e-8)
    write(out/(arm+"-evaluated.json"),dict(start_peak_c=records[0]["peak_c"],cap_m=cap,
        best_peak_c=best["peak_c"],best_wire_m=best["wire_m"],selected=records.index(best),
        least_wire_at_start_peak_m=reverse,forward_3d=len(valid),candidates=records))


def comparison(args):
    source, upstream, atpython = (p.resolve() for p in (args.cases,args.upstream,args.atpython))
    version = subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()
    if version != UPSTREAM:
        raise ValueError("ATPlace checkout differs from the declared revision")
    out = args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    env = dict(os.environ,PYTHONPATH=os.pathsep.join(str(ROOT/p) for p in ("src","tools")),
               OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",MPLBACKEND="Agg")
    script = Path(__file__).resolve()
    upstream_script = script.with_name("atplace_shared_fv.py")
    hashes = hashlib.sha256()
    for path in ("src/chiplet_floorplanning/placement/thermal.py","src/chiplet_floorplanning/package.py",
                 "src/chiplet_floorplanning/mesh.py","src/chiplet_floorplanning/power.py", "tools/compare_atplace_margin.py"):
        hashes.update((ROOT/path).read_text(encoding="utf8").encode())
    result = dict(fv_fingerprint=hashes.hexdigest(), seed=20261119, upstream=version, cases={})
    for _,start,cap,meta in starting_cases(source):
        name = meta["name"]
        if name not in args.names:
            continue
        sub = out/name
        sub.mkdir(exist_ok=True)
        raw = (source/(name+".json")).read_bytes()
        p = Problem.from_imported(json.loads(raw))
        (sub/"source.json").write_bytes(raw)
        write(sub/"input.json",dict(name=name, cap_m=cap, start_um=start.centre_um.tolist(),
            angles=start.rotation_deg.tolist(),names=p.names,powers_w=p.power_w.tolist(),
            source_sha256=hashlib.sha256(raw).hexdigest(),upstream=version,fv_fingerprint=hashes.hexdigest()))
        timings, arms, failed = {}, {}, {}
        def run(label, argv):
            then = perf_counter()
            with (sub/(label+".log")).open("w",encoding="utf8") as log:
                run = subprocess.run(list(map(str,argv)),cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            timings[label] = perf_counter()-then
            if run.returncode:
                failed[label] = (sub/(label+".log")).read_text(encoding="utf8",errors="replace").splitlines()[-1]
            return run.returncode == 0
        def upstream_run(stage):
            return run(stage,[atpython,upstream_script,upstream,sub,stage,sys.executable])
        trained = upstream_run("train")
        for arm in ("shared","native","margin"):
            if arm != "margin" and not (trained and upstream_run(arm)):
                continue
            if run(arm+"-score",[sys.executable,script,"assess",sub,arm]):
                row = json.loads((sub/(arm+"-evaluated.json")).read_bytes())
                warm = timings[arm+"-score"] + timings.get(arm,0.)
                row.update(warm_s=warm,cold_total_s=warm+(timings["train"] if arm!="margin" else 0.))
                arms[arm]=row
        result["cases"][name] = dict(timings_s=timings,arms=arms,failures=failed,
            training=json.loads((sub/"training.json").read_bytes()) if trained else None)
        write(out/"results.json",result)
        print(name,{k:(round(r["best_peak_c"],3),round(r["cold_total_s"],2)) for k,r in arms.items()},failed,flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest="task",required=True)
    for task in ("labels","assess"):
        parser=sub.add_parser(task)
        parser.add_argument("out",type=Path)
        if task=="assess":
            parser.add_argument("arm",choices=["margin","shared","native"])
    parser=sub.add_parser("run")
    for flag in ("cases","upstream","atpython","output"):
        parser.add_argument("--"+flag,type=Path,required=True)
    parser.add_argument("--names",nargs="+",choices=NAMES,default=NAMES)
    args=ap.parse_args()
    if args.task=="run":
        comparison(args)
    elif args.task=="labels":
        labels(args.out)
    else:
        assess(args.out,args.arm)


if __name__=="__main__":
    main()
