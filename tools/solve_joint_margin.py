"""Compare simultaneous placement against anchored pairs at identical forward-field counts."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.common_move import HotspotResponse
from chiplet_floorplanning.placement.footprint_response import FootprintResponse
from chiplet_floorplanning.placement.joint_assignment import JointAssignment
from chiplet_floorplanning.placement.joint_generation import JointLandings
from chiplet_floorplanning.placement.joint_margin import PairMargin
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.relocation import Landing
from common_relocation import FOUR, TARGET, audit, freeze_action
from direct_relocation import physical_cost, rebuild, rules
from generate_joint_landings import action_key, generate, score_layout, thermal_start
from power_uncertainty import text_digest
from transfer_placement import starting_cases


EVIDENCE = Path(__file__).resolve().parents[1]/"docs/evidence"
HOLDOUT = EVIDENCE/"joint-margin/holdout-inputs.json"
BASELINE = EVIDENCE/"joint-generation/search.json"
ARMS = ("previous","tiled","hotspots","sparse")
EPS = 1e-8


def inputs(source, holdout):
    yield from starting_cases(source)
    if holdout:
        for name, row in json.loads(HOLDOUT.read_bytes())["cases"].items():
            xy = np.array(row["from_um"])
            n = len(xy)
            p = Problem(name, tuple(f"die_{k}" for k in range(n)), np.tile(row["size_um"],(n,1)),
                        np.full(n,.1*row["rated_w"]),tuple(row["carrier_um"]),
                        np.array(row["pin_chip"],int),np.array(row["pin_offset_um"]))
            start = Layout(xy,np.zeros(n,int))
            yield p,start,physical_cost(p,start,None),dict(family="RapidChiplet",cost_metric="pin_manhattan_m")


def starting_cells(p, sheet, field, tiled, sparse):
    cells = {tuple(map(int,np.unravel_index(field.argmax(), field.shape)))}
    if tiled:
        side = max(1, round(float(np.median(p.size_um.min(axis=1))) / 1000))
        if sparse:
            side = max(side,int(np.ceil(max(p.carrier_um)/4000)))
        x0,y0 = sheet.carrier_offset
        w,h = np.array(p.carrier_um)/1000
        low = np.searchsorted(sheet.edges[1:], (x0,y0), side="right")
        high = np.searchsorted(sheet.edges[:-1], (x0+w,y0+h), side="left")
        for y in range(low[1],high[1],side):
            for x in range(low[0],high[0],side):
                tile = field[y:min(y+side,high[1]),x:min(x+side,high[0])]
                j,i = np.unravel_index(tile.argmax(),tile.shape)
                cells.add((int(y+j),int(x+i)))
    return sorted(cells)


def choose(p,start,cap,meta,budget,*,tiled=True,sparse=False,cardinality=None,old_extended=False,time_limit_s=None):
    footprint,demand = rules(p,meta)
    domain = JointLandings(p,footprint,start,demand,cap)
    sheets,fields = thermal_start(p,start)
    peaks = [float(v.max()) for v in fields]
    seen = set()
    projection = None
    def observe(b,cell):
        nonlocal projection
        if (b,cell) not in seen:
            row = HotspotResponse.at_cell(sheets[b],fields[b],cell)
            seen.add((b,cell))
            if old_extended:
                domain.observe(row)
                return
            if projection is None:
                projection = FootprintResponse(domain,row)
            c = projection.cooling(row)
            if cardinality is None and len(domain.cooling)>=4 and c.size:
                # For any two sites, their summed difference is at least twice
                # its minimum. Such a row cannot limit any pair more than ref.
                if any(row.headroom_k-h+2*(c-ref).min()>EPS
                       for h,ref in zip(domain.headroom[:4],domain.cooling[:4])):
                    return
            domain.cooling.append(c)
            domain.headroom.append(row.headroom_k)
    for b,field in enumerate(fields):
        observe(b,tuple(map(int,np.unravel_index(field.argmax(),field.shape))))
    for b,(sh,f) in enumerate(zip(sheets,fields)):
        for cell in starting_cells(p,sh,f,tiled and not old_extended,sparse):
            observe(b,cell)
    initial_count = len(seen)
    if old_extended:
        domain.retain_contact_landings()
    elif cardinality is None:
        solver = PairMargin(domain)
    else:
        solver = JointAssignment(domain,*cardinality,time_limit_s=time_limit_s)
    history, excluded = [], set()
    stay = Landing((),(),domain.net.initial,0.)
    best_rank, best_move = (0.,stay.cost,()), stay
    certified_after = None
    for _ in range(budget):
        candidate = domain.propose(excluded,-np.inf) if old_extended else solver.propose(excluded)
        if candidate is None:
            if not (cardinality is not None and solver.incomplete) and certified_after is None:
                certified_after = len(history)
            break
        key,move,upper = candidate
        master_bound = solver.dual_upper_k if cardinality is not None else upper
        if master_bound < -best_rank[0]-EPS and certified_after is None:
            certified_after = len(history)
        if cardinality is not None and certified_after is not None:
            break
        excluded.add(key)
        gains,cells = score_layout(sheets,peaks,move.apply(start))
        b = int(np.argmin(gains))
        gain = gains[b]
        assert gain <= upper+EPS
        rank = (-gain,move.cost,key)
        if rank < best_rank:
            best_rank,best_move = rank,move
        new = (b,cells[b]) not in seen and gain < upper-EPS
        if new:
            observe(b,cells[b])
        history.append(dict(action=freeze_action(move,start,p),upper_k=upper,gains_k=gains,
                            limiting_boundary=FOUR[b],cell_yx=cells[b],added=bool(new)))
        if cardinality is not None:
            history[-1]["master_dual_upper_k"] = master_bound if np.isfinite(master_bound) else None
        if cardinality is not None and master_bound <= -best_rank[0]+EPS:
            certified_after = len(history)
            break
    raw = -best_rank[0]
    move = best_move if raw>TARGET else stay
    return dict(action=freeze_action(move,start,p),raw_action=freeze_action(best_move,start,p),
                gain_k=raw if move.chips else 0.,raw_k=raw,cap=cap,budget=budget,trace=history,
                checks=len(history),initial_observers=initial_count,added=len(seen)-initial_count,
                stored_rows=len(domain.cooling),
                certified_after=certified_after,
                incomplete_master=bool(cardinality is not None and solver.incomplete),
                scored_pairs=domain.scored_pairs if old_extended else getattr(solver,"pairs_scored",0),
                wire_cuts=0 if old_extended else getattr(solver,"wire_cuts",0))


def baseline(p,start,cap,meta):
    v = generate(p,start,cap,meta,9,True,retain_contacts=True)
    return dict(action=v["action"],raw_action=v["raw_action"],gain_k=v["gain_k"],raw_k=v["raw_k"],cap=cap,
                budget=9,checks=v["joint_evaluations"],trace=v["trace"],initial_observers=4,added=v["new_probes"],
                scored_pairs=v["scored_pairs"],stop=v["stop"])


def compare(source,repeat,holdout,only):
    old = json.loads(BASELINE.read_bytes())["cases"]["contacts"]
    quotas = {}
    records,times = {},{arm:[] for arm in ARMS}
    for trial in range(repeat):
        for arm in ARMS[trial%len(ARMS):]+ARMS[:trial%len(ARMS)]:
            begin = previous = perf_counter()
            cases,by_case = {},{}
            for p,start,cap,meta in inputs(source,holdout):
                n = p.name
                if only and n not in only:
                    continue
                if arm=="previous":
                    row = baseline(p,start,cap,meta)
                    if n in old:
                        assert action_key(old[n]["action"])==action_key(row["action"])
                        assert old[n]["joint_evaluations"]==row["checks"]
                    quotas[n] = row["checks"]
                else:
                    row = choose(p,start,cap,meta,quotas[n],tiled=arm!="hotspots",sparse=arm=="sparse")
                    assert quotas[n]==row["checks"], (n,row["checks"],quotas[n])
                cases[n] = row
                end = perf_counter()
                by_case[n] = end-previous
                previous = end
            elapsed = perf_counter()-begin
            if arm in records:
                assert records[arm]==cases
            else:
                records[arm]=cases
            times[arm].append(dict(total_s=elapsed, by_case_s=by_case))
            print(trial+1,arm,round(elapsed,3),flush=True)
    return dict(baseline_sha256=text_digest(BASELINE),holdout_sha256=text_digest(HOLDOUT),
                cases=records,times=times,actual_checks=quotas)


def old_first_choices(p,start,cap,meta,trace):
    f,demand = rules(p,meta)
    pool = JointLandings(p,f,start,demand,cap)
    sheets,fields = thermal_start(p,start)
    for sh,field in zip(sheets,fields):
        pool.observe(HotspotResponse.at_cell(sh,field,np.unravel_index(field.argmax(),field.shape)))
    pool.retain_contact_landings()
    ever = set(pool.anchors())
    for step in trace:
        if step["added"]:
            b = FOUR.index(step["limiting_boundary"])
            pool.observe(HotspotResponse.at_cell(sheets[b],fields[b],tuple(step["cell_yx"])))
            ever.update(pool.anchors())
    def coords(indices):
        return {(int(pool.chip[i]),tuple(pool.xy[i])) for i in indices}
    return coords(ever),coords(pool.retained),sheets,fields


def audit_run(source,path,holdout):
    s = json.loads(path.read_bytes())
    out = dict(search_sha256=text_digest(path),cases={})
    for p,start,cap,meta in inputs(source,holdout):
        n = p.name
        if n not in s["actual_checks"]:
            continue
        old = s["cases"]["previous"][n]
        ever,fixed,sheets,fields = old_first_choices(p,start,cap,meta,old["trace"])
        peaks = [float(v.max()) for v in fields]
        f,demand = rules(p,meta)
        rows,actions = {},{}
        for arm,by_case in s["cases"].items():
            r = by_case[n]
            action = r["action"]
            passing = []
            for step in r["trace"]:
                a = step["action"]
                layout = rebuild(start,a)
                assert is_legal(f,layout,100)
                cost = physical_cost(p,layout,demand)
                assert abs(cost-a["cost"])<1e-9 and cost<=cap+1e-9
                gs,_ = score_layout(sheets,peaks,layout)
                np.testing.assert_allclose(gs,step["gains_k"],rtol=0,atol=EPS)
                if min(gs)>TARGET:
                    passing.append(cost)
            gs,_ = score_layout(sheets,peaks,rebuild(start,action))
            assert abs(min(gs)-r["gain_k"])<EPS
            key = action_key(action)
            rows[arm] = dict(gain_k=min(gs),peak_above_ambient_k=dict(zip(FOUR,np.subtract(peaks,gs))),
                             wire=action["cost"],outside_all_first_choices=bool(key and ever.isdisjoint(key)),
                             outside_fixed_first_choices=bool(key and fixed.isdisjoint(key)),
                             outside_proposals=sum(ever.isdisjoint(action_key(st["action"])) for st in r["trace"]),
                             least_passing_wire=min(passing) if passing else None)
            actions[arm] = action
        pkg = audit(p,start,cap,meta,dict(actions=actions),grid=64)
        package = {}
        for arm in actions:
            cooling = {b:values[arm]["cooling_k"] for b,values in pkg["conditions"].items()}
            package[arm] = dict(four_k=min(cooling[b] for b in FOUR),centre_k=cooling["centre"])
        out["cases"][n]=dict(arms=rows,package=package,cap=cap,metric=meta["cost_metric"],first_choices=len(ever))
        if n=="Case4":
            challenge = json.loads((EVIDENCE/"joint-generation/audit.json").read_bytes())
            known = max(challenge["cases"][n]["one_step_challenge"],key=lambda v:v["gain_k"])
            out["case4_counterexample"]=dict(known=known,both_outside=ever.isdisjoint(action_key(known["action"])),
                equal_eight={arm:choose(p,start,cap,meta,8,old_extended=arm=="previous") for arm in ("previous","tiled")})
        if n=="Case5":
            out["simultaneous_case5"]={str(k):choose(p,start,cap,meta,8,cardinality=(2,2) if k==2 else (1,p.count))
                                      for k in (2,p.count)}
            selected = {k:v["action"] for k,v in out["simultaneous_case5"].items()}
            for k,action in selected.items():
                layout = rebuild(start,action)
                assert is_legal(f,layout,100) and abs(physical_cost(p,layout,demand)-action["cost"]) < 1e-9
                assert action["cost"]<=cap+1e-9
                assert abs(min(score_layout(sheets,peaks,layout)[0])-out["simultaneous_case5"][k]["gain_k"]) < EPS
            out["simultaneous_package"] = audit(p,start,cap,meta,dict(actions=selected),grid=64)["conditions"]
        if n=="RC-mesh-3x4":
            # A separate cold-start all-die test, with the same pin netlist and placement grid.
            r = choose(p,start,cap,meta,4,sparse=True,cardinality=(1,p.count),time_limit_s=5.)
            action=r["action"]
            layout=rebuild(start,action)
            assert is_legal(f,layout,100) and abs(physical_cost(p,layout,demand)-action["cost"])<1e-9
            assert action["cost"]<=cap+1e-9 and abs(min(score_layout(sheets,peaks,layout)[0])-r["gain_k"])<EPS
            out["simultaneous_holdout"] = r
            out["simultaneous_holdout_package"] = audit(
                p,start,cap,meta,dict(actions=dict(all_dies=action)),grid=64)["conditions"]
        print(n,flush=True)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--repeat",type=int,default=3)
    ap.add_argument("--development",action="store_true")
    ap.add_argument("--only",nargs="+")
    ap.add_argument("--audit",type=Path)
    a=ap.parse_args()
    data = audit_run(a.cases,a.audit,not a.development) if a.audit else compare(a.cases,a.repeat,not a.development,a.only)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n",encoding="utf8",newline="\n")


if __name__=="__main__":
    main()
