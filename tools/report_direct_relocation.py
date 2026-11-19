"""Summarize paired floorplan decisions and draw the frozen Case3 move."""

import argparse
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement import Layout
from chiplet_floorplanning.placement.geometry import boxes
from power_uncertainty import cases, text_digest


def summarize(rows):
    report = {}
    for arm in ("direct", "hottest", "shortest", "random", "opposite"):
        gains = [x["choices"][arm]["cooling_k"] for x in rows if arm in x["choices"]]
        paired = [x["choices"]["direct"]["cooling_k"] - x["choices"][arm]["cooling_k"]
                  for x in rows if arm in x["choices"]]
        report[arm] = dict(count=len(gains), cooled_over_0p1=sum(v > .1 for v in gains),
                           warmed_over_0p1=sum(v < -.1 for v in gains), median_cooling_k=median(gains),
                           median_direct_minus_arm_k=median(paired), direct_wins_over_0p1=sum(v > .1 for v in paired),
                           arm_wins_over_0p1=sum(v < -.1 for v in paired))
    return report


def figure(problem, locked, actual, trials, out):
    fig, (ax, bars) = plt.subplots(1, 2, figsize=(10, 5.2), width_ratios=(1, 1.24), layout="constrained")
    start = Layout(np.array(locked["anchor_xy_um"]), np.array(locked["rotation_deg"]))
    chosen = locked["groups"]["strict"]["choices"]["direct"]
    i = chosen["indices"][0]
    for j, (x, y, u, v) in enumerate(boxes(problem, start)/1000):
        edge = "#bc3e35" if problem.names[j] == actual["start"]["hottest_die"] else "#57646f"
        ax.add_patch(Rectangle((x,y), u-x, v-y, facecolor="#e0e5e9" if j != i else "#cadbe9", edgecolor=edge,
                               linewidth=2 if edge == "#bc3e35" else 1))
        if j != i:
            ax.text((x+u)/2, (y+v)/2, problem.names[j], ha="center", va="center", fontsize=7)
    old, new = (np.array(chosen[k][0])/1000 for k in ("from_um", "to_um"))
    x,y,u,v = boxes(problem, start)[i]/1000
    ax.add_patch(Rectangle(new-(np.array([u-x,v-y])/2),u-x,v-y, fill=False, edgecolor="#007762", ls="--",lw=2))
    ax.annotate("", new, old, arrowprops=dict(arrowstyle="-|>", lw=2.2, color="#007762", mutation_scale=15))
    ax.annotate(problem.names[i], old, xytext=(0,7), textcoords="offset points", ha="center", fontsize=8)
    ax.set(xlim=(0,problem.carrier_um[0]/1000), ylim=(0,problem.carrier_um[1]/1000), aspect="equal",
           xlabel="Carrier x (mm)", ylabel="Carrier y (mm)")
    ax.set_title("Case3  |  Strict interconnect cap", loc="left", fontsize=12, fontweight="bold", pad=12)
    ax.text(0, -.19, "Red outline: original hottest chiplet\nGreen arrow: locked move and destination",
            transform=ax.transAxes, fontsize=9, va="top")
    names = [x["name"] for x in trials]
    y = np.arange(len(names))
    for cap, shift, marker, color, label in (("strict", -.14, "o", "#007762", "Starting distance cap"),
                                             ("published", .14, "D", "#5a6cab", "Published cap")):
        gain = [x["groups"][cap]["choices"]["direct"]["cooling_k"] for x in trials]
        bars.scatter(gain, y+shift, s=29, marker=marker, color=color, label=label)
    bars.axvline(.1, color="#647076", ls="--", lw=.8)
    bars.set(yticks=y, yticklabels=names, xlabel="Peak reduction from starting layout (K)")
    bars.invert_yaxis()
    bars.grid(axis="x", alpha=.2)
    bars.set_title("One locked move per case and cap", loc="left", fontsize=12, fontweight="bold", pad=12)
    bars.legend(loc="upper center", bbox_to_anchor=(.5,-.12), ncol=2, fontsize=8, frameon=False)
    fig.savefig(out, dpi=180, facecolor="white", bbox_inches="tight", pad_inches=.15)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    args = ap.parse_args()
    path = args.evidence / "predictions.json"
    frozen = json.loads(path.read_bytes())["cases"]
    actual = json.loads((args.evidence / "package.json").read_bytes())
    assert actual["predictions_sha256"] == text_digest(path)
    rows = actual["cases"]
    by_cap = {b: [] for b in ("strict", "published")}
    unique = []
    for pred, result in zip(frozen, rows, strict=True):
        assert pred["name"] == result["name"]
        seen = []
        for b, g in pred["groups"].items():
            row = result["groups"][b]
            by_cap[b].append(row)
            if not any(abs(cap-g["cap"]) <= 1e-9 for cap in seen):
                unique.append(row)
            seen.append(g["cap"])
    scores = [x for case in rows + actual["refinement"] for g in case["groups"].values()
              for x in [case["start"], *g["choices"].values()]]
    report = dict(by_cap={b:summarize(rs) for b, rs in by_cap.items()}, distinct_case_and_cap=summarize(unique),
                  length_at_0p1k=[dict(case=c["name"], cap=b, arm=g["shortest_at_cooling_target"],
                                      cost=g["choices"].get(g["shortest_at_cooling_target"], {}).get("cost"))
                                  for c in rows for b, g in c["groups"].items()],
                  max_imbalance_w=max(abs(s["heat_w"]-s["removed_w"]) for s in scores),
                  max_residual_w=max(s["residual_w"] for s in scores))
    (args.evidence / "summary.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8", newline="\n")
    case_id = next(i for i, c in enumerate(rows) if c["name"] == "Case3")
    p = next(p for p, _, _ in cases(args.cases) if p.name == "Case3")
    figure(p, frozen[case_id], rows[case_id], rows, args.evidence / "moves.png")


if __name__ == "__main__":
    main()
