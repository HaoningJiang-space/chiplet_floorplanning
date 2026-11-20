"""Compare fixed-power floorplans to the best possible allocation on their occupied source cells."""

import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package, checked_solution, require_heat_path, solve_spd
from chiplet_floorplanning.power import rasterize
from common_relocation import ORIGINAL, TARGET
from direct_relocation import rebuild
from power_uncertainty import cases, text_digest
from relocation_contact import contact_model


def two_site_check():
    """Exhaust the two-source assignment on three small reciprocal networks and reverse it with a third load."""
    results = {}
    coords = {"chain":[(i,0,0) for i in range(6)],
              "square":[(i,j,0) for i in range(3) for j in range(3)],
              "cube":[(i,j,k) for i in range(2) for j in range(2) for k in range(2)]}
    for name,nodes in coords.items():
        n = len(nodes)
        xy = np.array(nodes)
        lap = np.zeros((n,n))
        for i,j in combinations(range(n),2):
            if abs(xy[i]-xy[j]).sum() == 1:
                g = 1. + (i+j)%3
                lap[i,i] += g
                lap[j,j] += g
                lap[i,j] = lap[j,i] = -g
        trials,maximum_excess = 0,0.
        for sink in (np.ones(n),np.linspace(.25,2.,n),.1+np.eye(n)[0]):
            matrix = lap+np.diag(sink)
            response = np.linalg.solve(matrix,np.eye(n))
            for i,j in combinations(range(n),2):
                a,b = sorted((i,j),key=lambda k:response[k,k])
                p = np.zeros(n)
                p[a],p[b] = 3.,1.
                preferred = np.linalg.solve(matrix,p).max()
                p[a],p[b] = 1.,3.
                reverse = np.linalg.solve(matrix,p).max()
                maximum_excess = max(maximum_excess,preferred-reverse)
                trials += 1
        assert maximum_excess < 1e-10
        results[name] = dict(assignments_compared=trials,max_violation_k=maximum_excess)
    matrix = np.array([[4.,-1.,-1.],[-1.,2.,0.],[-1.,0.,1.]])
    response = np.linalg.solve(matrix,np.eye(3))
    cases = {k:[np.linalg.solve(matrix,[high,low,k]).tolist() for high,low in ((3,1),(1,3))] for k in (0,1)}
    assert response[0,0] < response[1,1] and max(cases[0][0]) < max(cases[0][1])
    assert max(cases[1][0]) > max(cases[1][1])
    return dict(networks=results, background_example=dict(matrix_w_k=matrix.tolist(),
                self_k_w=np.diag(response).tolist(),rise_k_by_third_source_w=cases))


def source_limits(matrix, rhs, sink, *, check_optimum):
    active = rhs > 0.
    passive = ~active
    unit = active.astype(float)
    unit[passive] = solve_spd(matrix[passive][:,passive], -(matrix @ unit)[passive])
    unit_flux = matrix @ unit
    conductance = unit_flux[active]
    total = float(conductance.sum())
    assert total > 0 and min(conductance) >= -1e-10
    ideal_rhs = np.zeros_like(rhs)
    ideal_rhs[active] = conductance
    checked_solution(matrix,ideal_rhs,sink,unit)

    actual = solve_spd(matrix,rhs)
    checked_solution(matrix,rhs,sink,actual)
    peak = float(actual[active].max())
    floor = float(rhs.sum()/total)
    headroom = float(conductance @ (peak-actual[active])/total)
    assert abs(peak-actual.max()) < 1e-7
    assert abs(peak-floor-headroom) < 1e-6 and headroom >= -1e-7
    upper = float(np.max(rhs[active]/conductance)) if np.all(conductance>0) else None
    assert upper is None or upper >= peak-1e-6
    result = dict(source_cells=int(active.sum()), power_w=float(rhs.sum()), total_w_k=total,
                  ideal_rise_k=floor, actual_rise_k=peak, headroom_k=headroom, upper_rise_k=upper,
                  identity_error_k=abs(peak-floor-headroom))
    if check_optimum:
        matched = ideal_rhs * floor
        assert abs(matched.sum()-rhs.sum()) < 1e-7 and matched.min() >= -1e-9
        theta = solve_spd(matrix,matched)
        checked_solution(matrix,matched,sink,theta)
        result["matched_max_source_error_k"] = float(np.max(np.abs(theta[active]-floor)))
        assert result["matched_max_source_error_k"] < 1e-6
    return result


def audit(problem, pose, centre, reference, check_optimum):
    data = contact_model(problem,pose,64,np.array(centre,dtype=float))
    case = parse_case(data,node_limit=450000)
    heat,_ = rasterize(case)
    matrix,rhs,sink,*_ = assemble_package(case,heat)
    require_heat_path(matrix,sink)
    assert abs(rhs.sum()-problem.power_w.sum()) < 1e-7
    result = source_limits(matrix,rhs,sink,check_optimum=check_optimum)
    assert abs(result["actual_rise_k"]+case.thermal["ambient_c"]-reference["peak_c"]) < 1e-6
    return result


def compare(base, final):
    upper = final["upper_rise_k"]
    if base["actual_rise_k"] - final["ideal_rise_k"] <= TARGET:
        verdict = "excluded"
    elif upper is not None and base["actual_rise_k"] - upper > TARGET:
        verdict = "proved"
    else:
        verdict = "undecided"
    return dict(actual_gain_k=base["actual_rise_k"]-final["actual_rise_k"],
                ideal_floor_gain_k=base["ideal_rise_k"]-final["ideal_rise_k"],
                headroom_gain_k=base["headroom_k"]-final["headroom_k"],bound_verdict=verdict)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--common",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args = ap.parse_args()
    actions_path = args.common/"pair-predictions.json"
    measured_path = args.common/"pair-package.json"
    locations_path = args.common/"expanded-predictions.json"
    locked,reference,locations = (json.loads(f.read_bytes()) for f in (actions_path,measured_path,locations_path))
    assert reference["paired_sha256"] == text_digest(actions_path) and locked["expanded_sha256"] == text_digest(locations_path)
    assert locked["original_sha256"] == text_digest(ORIGINAL)
    centres = locations["known_xy_mm"] | locations["held_xy_mm"]
    report = dict(actions_sha256=text_digest(actions_path),reference_sha256=text_digest(measured_path),
                  two_site=two_site_check(),cases={})
    for (p,designs,meta),anchor in zip(cases(args.cases),json.loads(ORIGINAL.read_bytes())["cases"],strict=True):
        assert p.name==anchor["name"] and meta["bank_sha256"]==anchor["bank_sha256"]
        moves = locked["cases"][p.name]["actions"]
        if not moves["pair"]["chips"]:
            continue
        _,start,_ = min(designs,key=lambda x:x[0])
        np.testing.assert_array_equal(start.centre_um,anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg,anchor["rotation_deg"])
        problem = replace(p,power_w=p.power_w*.1)
        poses = {"start":start,**{arm:rebuild(start,m) for arm,m in moves.items()}}
        frozen = reference["cases"][p.name]
        worst = next(iter(frozen["worst96"]["conditions"]))
        rows = {}
        for pos,conditions in frozen["grid64"]["conditions"].items():
            scores = {arm:audit(problem,poses[arm],centres[pos],v,pos==worst and arm in ("start","pair"))
                      for arm,v in conditions.items()}
            rows[pos] = dict(scores=scores,changes={k:compare(scores["start"],v) for k,v in scores.items() if k!="start"})
        report["cases"][p.name] = rows
        print(p.name,flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
