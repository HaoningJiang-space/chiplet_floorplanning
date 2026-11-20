"""Bound the peak reduction of already frozen layouts over a continuous top convection range."""

import argparse
from dataclasses import replace
from functools import cache
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.thermal import die_peaks_c, solve
from common_relocation import ORIGINAL, TARGET
from direct_relocation import physical_cost, rebuild, rules
from power_uncertainty import cases, text_digest
from relocation_contact import contact_model


def bound_contact(peaks, low=16000, high=24000, max_depth=3):
    """Each layout peak decreases with h. The *difference* need not be monotone."""
    samples = {}

    def sample(h):
        if h not in samples:
            start, moved = peaks(h)
            samples[h] = dict(start_c=start, moved_c=moved, gain_k=start-moved)
        return samples[h]

    nominal = sample((low+high)//2)
    leaves = []

    def visit(a, b, depth):
        left, right = sample(a), sample(b)
        lower = right["start_c"] - left["moved_c"]
        if lower > TARGET:
            status = "pass"
        elif min(row["gain_k"] for h,row in samples.items() if a <= h <= b) <= TARGET:
            status = "witness"
        elif depth == max_depth:
            status = "unresolved"
        else:
            mid = (a+b)//2
            visit(a,mid,depth+1)
            visit(mid,b,depth+1)
            return
        leaves.append(dict(h_low=a,h_high=b,lower_k=lower,status=status))

    visit(low,high,0)
    ordered = sorted(samples)
    for i,j in zip(ordered,ordered[1:]):
        for name in ("start_c","moved_c"):
            assert samples[i][name] >= samples[j][name]-1e-8
    status = ("witness" if any(x["status"]=="witness" for x in leaves) else
              "pass" if all(x["status"]=="pass" for x in leaves) else "unresolved")
    worst = min(ordered,key=lambda h:samples[h]["gain_k"])
    return dict(status=status,lower_k=min(x["lower_k"] for x in leaves),
                unsplit_lower_k=samples[high]["start_c"]-samples[low]["moved_c"],
                worst_observed_h=worst,worst_observed_k=samples[worst]["gain_k"],nominal_k=nominal["gain_k"],
                leaves=leaves,samples=samples)


def audit_case(problem, start, actions, reference, centres):
    poses = {"start":start}
    poses.update({arm:rebuild(start,action) for arm,action in actions.items()})
    max_balance, max_residual = 0.,0.

    @cache
    def score(arm, pos, h, grid):
        nonlocal max_balance,max_residual
        pose = poses[arm]
        case = contact_model(problem,pose,grid,np.asarray(centres[pos],dtype=float))
        case["thermal"]["top_h_w_m2k"] = h
        summary,rise,edges = solve(case,node_limit=450000)
        max_balance = max(max_balance,abs(summary["energy_balance_error_w"]))
        max_residual = max(max_residual,summary["linear_residual_inf_w"])
        assert abs(summary["source_power_w"]-problem.power_w.sum()) < 1e-7
        dies = die_peaks_c(problem,pose,rise,edges)
        peak = summary["peak_power_layer_c"]
        hot = problem.names[int(dies.argmax())] if abs(dies.max()-peak)<1e-7 else None
        return dict(peak_c=peak,hottest_die=hot)

    def at(pos, grid):
        return bound_contact(lambda h:tuple(score(arm,pos,h,grid)["peak_c"] for arm in ("start","pair")))

    results = {b:at(b,64) for b in centres}
    for b in centres:
        for arm,field in (("start","start_c"),("pair","moved_c")):
            assert abs(results[b]["samples"][20000][field]-reference[b][arm]["peak_c"]) < 1e-6
    worst = min(results,key=lambda b:results[b]["worst_observed_k"])
    fine = at(worst,96)
    mechanism = {}
    if problem.name == "Case9":
        for b in ("12/-1,1","12/1,-1"):
            mechanism[b] = {a:score(a,b,20000,64) for a in ("start","part1","part2","pair")}
    xy = actions["pair"]
    distances = {k:float(np.linalg.norm(np.diff(np.array(xy[k])/1000,axis=0))) for k in ("from_um","to_um")}
    return dict(status="moved", grid64=results,refined_position=worst,grid96=fine,
                pair_separation_mm=dict(before=distances["from_um"],after=distances["to_um"]),
                component_replay=mechanism,max_balance_w=max_balance,max_residual_w=max_residual,solves=score.cache_info().currsize)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--common",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args = ap.parse_args()
    selected,scored,contacts = (args.common/(name+".json") for name in
                                ("pair-predictions","pair-package","expanded-predictions"))
    locked,prior,where = (json.loads(path.read_bytes()) for path in (selected,scored,contacts))
    assert prior["paired_sha256"] == text_digest(selected) and locked["original_sha256"] == text_digest(ORIGINAL)
    assert locked["expanded_sha256"] == text_digest(contacts)
    centres = where["known_xy_mm"] | where["held_xy_mm"]
    report = dict(selections_sha256=text_digest(selected),prior_results_sha256=text_digest(scored),
                  h_range_w_m2k=[16000,24000],power_fraction=.1,target_k=TARGET,cases={})
    anchors = json.loads(ORIGINAL.read_bytes())["cases"]
    for (p,designs,meta),anchor in zip(cases(args.cases),anchors,strict=True):
        assert p.name == anchor["name"] and meta["bank_sha256"] == anchor["bank_sha256"]
        actions = locked["cases"][p.name]["actions"]
        if not actions["pair"]["chips"]:
            report["cases"][p.name] = dict(status="unchanged",gain_k=0.)
            continue
        _,start,cap = min(designs,key=lambda t:t[0])
        np.testing.assert_array_equal(start.centre_um,anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg,anchor["rotation_deg"])
        footprint,demand = rules(p,meta)
        for a in actions.values():
            pose = rebuild(start,a)
            cost = physical_cost(p,pose,demand)
            assert is_legal(footprint,pose,100) and cost <= cap+1e-9 and abs(cost-a["cost"]) < 1e-9
        result = audit_case(replace(p,power_w=.1*p.power_w),start,actions,prior["cases"][p.name]["grid64"]["conditions"],centres)
        report["cases"][p.name] = result
        print(p.name,result["solves"],flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
