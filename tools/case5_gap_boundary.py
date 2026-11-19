"""Replay the Case5 timing reversal under cooling and minimum-clearance changes."""

import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import boxes, pin_manhattan_um
from chiplet_floorplanning.placement.lp import legalize_relations
from cut_traffic import EVIDENCE
from thermal_role_transfer import compare, inputs


def check(source, gap_um):
    entry = next(
        e
        for e in json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
        if e["case"] == "Case5"
    )
    problem = Problem.from_imported(json.loads(source.read_bytes()))
    sites = sorted(range(len(problem.names)), key=lambda i: (-problem.power_w[i], i))[:4]
    rows, rejected = [], []
    for geometry in entry["layouts"]:
        if geometry["length_m"] > entry["length_cap_m"]:
            continue
        layout = Layout(np.array(geometry["centre_um"]), np.array(geometry["rotation_deg"]))
        if gap_um:
            repaired = legalize_relations(problem, layout, gap_um)
            if repaired is None:
                rejected.append(dict(layout=geometry["layout"], reason="nearest repair unavailable"))
                continue
            assert is_legal(problem, repaired, gap_um)
            length = float(pin_manhattan_um(problem, repaired).sum() / 1e6)
            if length > entry["length_cap_m"]:
                rejected.append(
                    dict(layout=geometry["layout"], length_m=length, reason="pin length above cap")
                )
                continue
            layout = repaired
            geometry = dict(geometry, centre_um=layout.centre_um.tolist(), length_m=length)
        rects = boxes(problem, layout)
        a, b = np.triu_indices(len(rects), 1)
        # Greatest separating axis distance per pair matches the repo's x-or-y gap rule.
        gaps = np.maximum(rects[a, :2] - rects[b, 2:], rects[b, :2] - rects[a, 2:]).max(axis=1)
        for boundary in ("nominal", "half_top", "two_sided"):
            meta, model = inputs(entry, source, boundary, 64, geometry=geometry, fixed_sites=sites)
            for dwell in (0.005, 0.05):
                run = compare(meta, model, dwell, 8, replay_all=True)
                row = next(p for p in run["peaks"] if p["pair"] == [0, 3])
                rows.append(
                    dict(
                        **meta,
                        dwell_s=dwell,
                        substeps=8,
                        min_axis_gap_um=float(gaps.min()),
                        steady_peak_c=run["steady_peak_c"],
                        centre_um=geometry["centre_um"],
                        rotation_deg=geometry["rotation_deg"],
                        **row,
                    )
                )
    return dict(gap_um=gap_um, rejected=rejected, rows=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--gap-um", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.case, args.gap_um)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
