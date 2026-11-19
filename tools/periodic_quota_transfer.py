"""Change work shares while holding floorplans and per-task heating fixed."""
import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.periodic import cycle_trace, periodic_pulse, quota_orders, quota_peak
from cut_traffic import EVIDENCE
from periodic_layout_choice import SLOTS, atplace_inputs, package_model


def layouts_at_quotas(inputs, substeps):
    rows = {k: [] for k in range(1, SLOTS)}
    for layout, length, data in inputs:
        g, capacity, rhs, _, nodes, ambient = package_model(data)
        steady, pulse = periodic_pulse(g, capacity, rhs, .05, substeps, SLOTS)
        steady, pulse = steady[nodes]+ambient, pulse[:, nodes]
        for k, records in rows.items():
            fraction = k/SLOTS
            mean = (1-fraction)*steady[:, 0] + fraction*steady[:, 1]
            peaks = {}
            for order in quota_orders(SLOTS, k):
                trace = cycle_trace(steady[:, 0], pulse, order)
                np.testing.assert_allclose(trace.mean(0), mean, rtol=0, atol=1e-8)
                peaks[order] = float(trace.max())
            assert abs(quota_peak(steady[:, 0], pulse, SLOTS, k)-max(peaks.values())) < 1e-8
            even = "".join(str((i+1)*k//SLOTS-i*k//SLOTS) for i in range(SLOTS))
            even = min(even[i:]+even[:i] for i in range(SLOTS))
            records.append(dict(layout=layout, length_m=length, floor_c=float(mean.max()), even_order=even,
                                even_c=peaks[even], best_c=min(peaks.values()), worst_c=max(peaks.values()),
                                peaks_c=peaks))
    return rows


def decide(rows):
    ordered = sorted(rows, key=lambda r: (r["floor_c"], r["length_m"], r["layout"]))
    key = lambda r: (r["best_c"], r["length_m"], r["layout"])
    exhaustive = min(rows, key=key)
    winner, solved = None, []
    for row in ordered:
        # Strict inequality also honors the wirelength tie break among equal peaks.
        if winner and row["floor_c"] > winner["best_c"] + 1e-9:
            break
        solved.append(row["layout"])
        if winner is None or key(row) < key(winner):
            winner = row
    assert winner["layout"] == exhaustive["layout"]
    return dict(simple_layout=ordered[0]["layout"], simple_c=ordered[0]["even_c"],
                joint_layout=winner["layout"], joint_c=winner["best_c"],
                simple_loss_k=ordered[0]["even_c"]-winner["best_c"], evaluated_layouts=solved)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--refine", type=Path, help="recheck the case with largest simple-policy loss in this screen")
    args = ap.parse_args()
    source = json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    grid, substeps = 32, 2
    if args.refine:
        screen = json.loads(args.refine.read_bytes())
        name = max(screen["cases"], key=lambda r:max(q["decision"]["simple_loss_k"] for q in r["quotas"]))["case"]
        source = [r for r in source if r["case"] == name]
        grid, substeps = 64, 8
    out = []
    for r in source:
        name = r["case"]
        inputs = atplace_inputs(args.cases/(name+".json"), r, grid)
        quotas = layouts_at_quotas(inputs, substeps)
        out.append(dict(case=name, length_cap_m=r["length_cap_m"],
                        quotas=[dict(count=k, decision=decide(v), layouts=v) for k,v in quotas.items()]))
        print(name, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(grid=grid, substeps=substeps, slot_s=.05, cases=out),
                                      indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
