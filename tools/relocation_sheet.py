"""Use a fixed cooled-sheet heat response to pick one feasible landing before a 3-D package audit."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.relocation import ConnectionCost, landing_bank, select_landing
from chiplet_floorplanning.placement.thermal import solve
from direct_relocation import physical_cost, rebuild, rules
from power_uncertainty import cases, text_digest
from relocation_contact import contact_centres, contact_model


def propose(p, start, bank, cap, centre):
    sheet = CooledSheet(p, centre)
    feasible = [replace(point, rise_k=sheet.peak(point.apply(start))) for point in bank if point.cost <= cap+1e-9]
    chosen = select_landing(feasible, cap)
    return dict(chips=[p.names[i] for i in chosen.chips], indices=chosen.chips,
                from_um=start.centre_um[list(chosen.chips)].tolist(), to_um=chosen.destinations_um,
                cost=chosen.cost, centre_package_mm=centre.tolist(), candidate_count=len(feasible),
                predicted_cooling_k=feasible[0].rise_k - chosen.rise_k)


def verify(p, start, meta, cap, centre, old, locked):
    footprint_problem, demand = rules(p, meta)
    np.testing.assert_allclose(centre, locked["centre_package_mm"], rtol=0, atol=1e-10)
    cache = {}
    results = {}
    for arm, layout in (("start", start), ("half_space", rebuild(start, old)), ("sheet", rebuild(start, locked))):
        cost = physical_cost(p, layout, demand)
        assert is_legal(footprint_problem, layout, 100) and cost <= cap+1e-9
        key = layout.centre_um.tobytes()
        if key not in cache:
            summary, _, _ = solve(contact_model(p, layout, 96, centre), node_limit=450000)
            cache[key] = summary
        results[arm] = dict(cost=cost, **cache[key])
    for v in results.values():
        v["cooling_k"] = results["start"]["peak_power_layer_c"] - v["peak_power_layer_c"]
    return dict(arms=results, distinct_solves=len(cache))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--audit", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    original = json.loads(args.predictions.read_bytes())
    report = dict(original_sha256=text_digest(args.predictions), power_fraction=.1, cases={})
    if args.audit:
        locked = json.loads(args.audit.read_bytes())
        assert locked["original_sha256"] == report["original_sha256"]
        report["sheet_predictions_sha256"] = text_digest(args.audit)
    for (p, designs, meta), case in zip(cases(args.cases), original["cases"], strict=True):
        if p.name not in ("Case1", "Case3", "ascend910"):
            continue
        _, start, cap = min(designs, key=lambda x: x[0])
        assert p.name == case["name"] and abs(cap-case["groups"]["strict"]["cap"]) < 1e-9
        np.testing.assert_array_equal(start.centre_um, case["anchor_xy_um"])
        p = replace(p, power_w=p.power_w * report["power_fraction"])
        old = case["groups"]["strict"]["choices"]["direct"]
        if not args.audit:
            footprint_problem, demand = rules(p, meta)
            bank, _ = landing_bank(p, footprint_problem, start, ConnectionCost(p, start, demand))
        result = {}
        for end, centre in contact_centres(p, old).items():
            if args.audit:
                result[end] = verify(p, start, meta, cap, centre, old, locked["cases"][p.name][end])
            else:
                result[end] = propose(p, start, bank, cap, centre)
        report["cases"][p.name] = result
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
