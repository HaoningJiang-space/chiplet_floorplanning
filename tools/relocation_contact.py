"""Challenge two frozen translations with the same cooled contact on either side of the move."""

import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.thermal import solve, thermal_case_data
from direct_relocation import rebuild
from power_uncertainty import cases, text_digest


def contact_centres(problem, action):
    old, new = (np.array(action[k][0]) / 1000 for k in ("from_um", "to_um"))
    unit = (new - old) / np.linalg.norm(new - old)
    midpoint = (new + old)/2 + (200 - np.array(problem.carrier_um)/1000)/2
    return {"origin_side": midpoint - 10*unit, "destination_side": midpoint + 10*unit}


def contact_model(problem, layout, grid, centre):
    data = thermal_case_data(problem, layout, 100, grid, top_h_w_m2k=20000)
    sink = data["thermal"]["layers"][-1]
    assert sink["id"] == "sink"
    sink["rect_mm"] = dict(x=centre[0]-15, y=centre[1]-15, width=30, height=30)
    return data


def challenge(problem, start, action):
    moved = rebuild(start, action)
    placements = {}
    for label, centre in contact_centres(problem, action).items():
        scored = {}
        for grid in (64, 96):
            row = {}
            for name, layout in (("start", start), ("direct", moved)):
                data = contact_model(problem, layout, grid, centre)
                summary, _, _ = solve(data, node_limit=450000)
                row[name] = summary
            row["cooling_k"] = row["start"]["peak_power_layer_c"] - row["direct"]["peak_power_layer_c"]
            scored[grid] = row
        placements[label] = dict(centre_package_mm=centre.tolist(), grids=scored)
    return placements


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--predictions", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    pred = json.loads(args.predictions.read_bytes())
    result = dict(predictions_sha256=text_digest(args.predictions), cooling_area_mm2=900, top_h_w_m2k=20000, cases={})
    for (p, designs, meta), locked in zip(cases(args.cases), pred["cases"], strict=True):
        if p.name in ("Case1", "ascend910"):
            idx, start, _ = min(designs, key=lambda x: x[0])
            assert locked["anchor_id"] == idx and locked["bank_sha256"] == meta["bank_sha256"]
            np.testing.assert_array_equal(start.centre_um, locked["anchor_xy_um"])
            np.testing.assert_array_equal(start.rotation_deg, locked["rotation_deg"])
            action = locked["groups"]["strict"]["choices"]["direct"]
            result["cases"][p.name] = challenge(p, start, action)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
