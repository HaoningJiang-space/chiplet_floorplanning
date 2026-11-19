"""Swap equal-mean chiplets on fixed footprints, preserving individual signal identities."""
import argparse
from collections import defaultdict
from dataclasses import replace
from itertools import permutations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.thermal import die_peaks_c, solve, thermal_case_data
from cut_traffic import EVIDENCE, digest
from periodic_layout_choice import ALTERNATE, package_model, trial


def experiment(source, entry, grid, substeps):
    assert digest(source) == entry["input_sha256"]
    problem = Problem.from_imported(json.loads(source.read_bytes()))
    types = defaultdict(list)
    for i, name in enumerate(problem.names):
        types[(name.rsplit("_", 1)[0], tuple(problem.size_um[i]), problem.power_w[i])].append(i)
    sites = np.array(max((v for v in types.values() if len(v)>=4), key=lambda v: problem.power_w[v[0]])[:4])
    anchor = min(entry["layouts"], key=lambda r: (r["length_m"], r["layout"]))
    base = Layout(np.array(anchor["centre_um"]), np.array(anchor["rotation_deg"]))
    feasible, representatives = [], {}
    for perm in permutations(sites.tolist()):
        centre, rotation = base.centre_um.copy(), base.rotation_deg.copy()
        centre[sites], rotation[sites] = centre[list(perm)], rotation[list(perm)]
        layout = Layout(centre, rotation)
        assert is_legal(problem, layout, 0)
        wire = float(pin_manhattan_um(problem, layout).sum()/1e6)
        if wire > entry["length_cap_m"]:
            continue
        pair = tuple(sorted(perm[:2]))
        feasible.append(dict(assign_sites=perm, wire_m=wire))
        if pair not in representatives or wire < representatives[pair][0]:
            representatives[pair] = (wire, layout, perm)

    mean = .25 * problem.power_w
    mean[sites] = .6 * problem.power_w[sites]
    powers = np.tile(mean, (2,1))
    powers[:, sites[0]] = [.2 * problem.power_w[sites[0]], problem.power_w[sites[0]]]
    powers[:, sites[1]] = powers[::-1, sites[0]].copy()
    np.testing.assert_allclose(powers.mean(0), mean)
    mean_data = thermal_case_data(replace(problem, power_w=mean), base, 0, grid)
    obs, rise, edges = solve(mean_data)
    mesh = parse_case(mean_data).mesh
    site_peaks = die_peaks_c(problem, base, rise, edges)
    mean_model = package_model([mean_data])
    records = []
    for pair, (wire, layout, perm) in sorted(representatives.items()):
        data = [thermal_case_data(replace(problem, power_w=w), layout, 0, grid) for w in powers]
        assert all(parse_case(d).mesh == mesh for d in data)
        model = package_model(data)
        assert (model[0] != mean_model[0]).nnz == 0
        np.testing.assert_allclose(model[1], mean_model[1])
        np.testing.assert_allclose(model[2].mean(1), mean_model[2][:,0], rtol=1e-12, atol=1e-12)
        run = trial(model, .05, substeps, audit=not records)
        assert abs(obs["peak_power_layer_c"]-run["mean_peak_c"]) < 1e-6
        records.append(dict(pair=list(pair), assigned_sites=perm, wire_m=wire, warmest_site_c=max(site_peaks[list(pair)]),
                            even_peak_c=run["peaks_c"][ALTERNATE], **run))
    short = min(records, key=lambda r:(r["wire_m"],r["pair"]))
    cool = min(records, key=lambda r:(r["warmest_site_c"],r["wire_m"],r["pair"]))
    best = min(records, key=lambda r:(r["best_peak_c"],r["wire_m"],r["pair"]))
    return dict(case=entry["case"], grid=grid, substeps=substeps, anchor_layout=anchor["layout"],
                sites=[problem.names[i] for i in sites], length_cap_m=entry["length_cap_m"],
                mean_peak_c=obs["peak_power_layer_c"], admissible=feasible, distinct_pairs=records,
                shortest_pair=short["pair"], headroom_pair=cool["pair"], best_pair=best["pair"],
                shortest_loss_k=short["even_peak_c"]-best["best_peak_c"],
                headroom_loss_k=cool["even_peak_c"]-best["best_peak_c"],
                assignment_range_k=max(r["best_peak_c"] for r in records)-best["best_peak_c"])


def draw_pair(result, problem, anchor, path):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle
    from chiplet_floorplanning.placement.geometry import boxes

    layout = Layout(np.array(anchor["centre_um"]), np.array(anchor["rotation_deg"]))
    outlines = boxes(problem, layout)/1000
    colors = ["#dee4e7", "#7da5b3", "#c36637"]
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 5.2), sharex=True, sharey=True)
    for ax, key, title in zip(axes, ["shortest_pair", "headroom_pair"], ["Shortest pin distance", "Largest thermal headroom"]):
        pair = result[key]
        chosen = next(r for r in result["distinct_pairs"] if r["pair"] == pair)
        for i, (x, y, x1, y1) in enumerate(outlines):
            kind = 2 if i in pair else int(problem.names[i] in result["sites"])
            ax.add_patch(Rectangle((x,y), x1-x, y1-y, facecolor=colors[kind], edgecolor="white", linewidth=.65))
            if kind == 2:
                ax.text((x1+x)/2, (y1+y)/2, str(i), ha="center", va="center", fontsize=8, color="white")
        w,h = np.array(problem.carrier_um)/1000
        ax.set(xlim=(0,w), ylim=(0,h), aspect="equal", xlabel="Carrier x (mm)")
        ax.set_title(f'{title}\n{chosen["even_peak_c"]:.2f} °C   |   {chosen["wire_m"]:.2f} m pins', fontsize=11)
    axes[0].set_ylabel("Carrier y (mm)")
    fig.suptitle(f'{result["case"]}  |  Same mean heat map, different active sites', fontsize=14)
    fig.legend([Patch(color=c) for c in colors], ["Other dies", "Constant at 60%", "Alternates 20–100%"],
               loc="lower center", ncol=3, frameon=False)
    fig.subplots_adjust(bottom=.16, top=.85, wspace=.12)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--transfer", action="store_true", help="run the six prespecified role-transfer cases")
    ap.add_argument("--recheck", help="replay a single case at 64 grid and eight steps per task")
    ap.add_argument("--figure", type=Path, help="draw the fine-grid pair next to its alternative")
    args = ap.parse_args()
    rows = {r["case"]:r for r in json.loads((EVIDENCE/"layout-dominance-v1.json").read_bytes())["cases"]}
    def run(name, grid, steps):
        return experiment(args.cases/(name+".json"), rows[name], grid, steps)
    names = ("Case2", "Case5", "Case6", "Case7", "Case9", "Case10") if args.transfer else ("Case3", "Case4", "Case8")
    if args.recheck:
        out = run(args.recheck, 64, 8)
    else:
        coarse = [run(n, 32, 2) for n in names]
        loss = "headroom_loss_k" if args.transfer else "shortest_loss_k"
        name = max(coarse, key=lambda r:r[loss])["case"]
        out = dict(coarse=coarse, fine=run(name, 64, 8))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if args.figure:
        result = out if args.recheck else out["fine"]
        name = result["case"]
        p = Problem.from_imported(json.loads((args.cases/(name+".json")).read_bytes()))
        anchor = next(r for r in rows[name]["layouts"] if r["layout"]==result["anchor_layout"])
        draw_pair(result, p, anchor, args.figure)


if __name__ == "__main__":
    main()
