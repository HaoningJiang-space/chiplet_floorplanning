"""Plot the locked joint floorplans and the audited two-dwell temperature tradeoff."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.geometry import boxes


def draw(axes, record, problem):
    floor, trade = axes
    name = record["case"]
    rows = record["layouts"]
    joint = record["arms"]["joint"]
    active = record["alternating_sites"]
    for key, initial in ((joint["selected"], False), (joint["initial"], True)):
        r = rows[key]
        layout = Layout(np.array(r["centre_um"]), np.array(r["rotation_deg"]))
        for die, (x, y, right, top) in zip(problem.names, boxes(problem, layout) / 1000):
            fill = "#d87c55" if die in active else "#cad7dd"
            floor.add_patch(Rectangle((x, y), right-x, top-y, facecolor="none" if initial else fill,
                                      edgecolor="#4c565c" if initial else "white",
                                      linestyle="--" if initial else "-", linewidth=.8))
            if not initial and die in active:
                floor.text((x+right)/2, (y+top)/2, die, ha="center", va="center", fontsize=8)
    width, height = np.asarray(problem.carrier_um) / 1000
    floor.set(xlim=(0, width), ylim=(0, height), aspect="equal", xlabel="Carrier x (mm)", ylabel="Carrier y (mm)",
              title=f"{name}  |  {joint['initial']} to {joint['selected']}")

    base = np.array(record["summary"]["pool_min_c"][:2])
    def points(keys):
        return (np.array([rows[k]["peaks_c"][:2] for k in keys]) - base).T
    trade.scatter(*points(rows), s=19, color="#a6b2b8", alpha=.8)
    trade.scatter(*points(record["initial_peaks_c"]), s=46, facecolor="none", edgecolor="#37454e", marker="s")
    styles = (("joint", "o", "#bc4e26", 110), ("short", "^", "#306d95", 68), ("long", "x", "#007a5e", 52))
    for arm, marker, color, size in styles:
        trade.scatter(*points([record["arms"][arm]["selected"]]), marker=marker,
                      s=size, color=color, linewidths=1.3, zorder=4)
    trade.add_patch(Rectangle((0, 0), .1, .1, fill=False, edgecolor="#5d475f", linewidth=1.2))
    trade.set(xlabel="5 ms peak above pool minimum (K)", ylabel="50 ms peak above pool minimum (K)",
              title=f"{name}  |  {len(rows)} audited geometries")
    trade.grid(alpha=.16)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--evidence", required=True, type=Path)
    ap.add_argument("--figure", required=True, type=Path)
    args = ap.parse_args()
    fig, axes = plt.subplots(2, 2, figsize=(9, 7.5))
    for name, pair in zip(("Case4", "Case5"), axes):
        result = json.loads((args.evidence / f"{name.lower()}.json").read_bytes())
        problem = Problem.from_imported(json.loads((args.cases / (name + ".json")).read_bytes()))
        draw(pair, result, problem)
    handles = [
        Line2D([], [], color="#4c565c", linestyle="--", label="Starting footprint"),
        Rectangle((0, 0), 1, 1, color="#d87c55", label="Alternating source"),
        Line2D([], [], marker="s", markerfacecolor="none", color="#37454e", linestyle="", label="Starting pool"),
        *(Line2D([], [], marker=m, color=c, linestyle="", label=s) for m, c, s in
          (("o", "#bc4e26", "Joint return"), ("^", "#306d95", "5 ms return"), ("x", "#007a5e", "50 ms return"))),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, .075, 1, 1), h_pad=2)
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.figure, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
