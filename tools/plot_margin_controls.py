"""Plot the two-die cancellation and the wire-budget counterexample from frozen results."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.evidence.read_bytes())
    chain = data["cases"]["chain_uniform"]
    initial = data["start"]
    sites = np.array(data["slots_um"]) / 1000.
    fig, (layout, gains, wires) = plt.subplots(1, 3, figsize=(12.5, 3.6),
                                               gridspec_kw={"width_ratios": [1.12, 1., 1.]},
                                               layout="constrained")
    teal, rust = "#0c746f", "#a54826"
    layout.set(title="Direct joint placement", xlabel="x (mm)", ylabel="y (mm)",
               xlim=(0, 53), ylim=(0, 27), aspect="equal")
    moving = {m["die"] for m in chain["joint_components"]}
    for idx, (x, y) in enumerate(sites):
        occupied = idx in initial
        die = initial.index(idx) if occupied else None
        color = teal if die in moving else "#50575e" if occupied else "#cad1d2"
        layout.add_patch(Rectangle((x-4, y-4), 8, 8, ec=color, lw=1.2, fill=occupied,
                                   facecolor=color, linestyle="-" if occupied else "--"))
        if occupied:
            layout.text(x, y, f"D{die}", color="white", ha="center", va="center", fontsize=9)
    for m in chain["joint_components"]:
        start, end = sites[[m["from_slot"], m["to_slot"]]]
        layout.annotate("", end, start+(end-start)*.31,
                        arrowprops=dict(arrowstyle="-|>", lw=2.2, color=rust))
    x = np.arange(3)
    for i, (name, color) in enumerate((("uniform", teal), ("heterogeneous", rust))):
        row = data["cases"]["chain_"+name]
        values = [m["single_worst_k"] for m in row["joint_components"]]
        values.append(row["cardinalities"][-1]["joint"]["gain_k"])
        gains.bar(x+(i-.5)*.35, values, .33, label=name.capitalize(), color=color)
    gains.axhline(0, color="#3a4344", lw=.8)
    gains.set(title="Worst-boundary peak reduction", xticks=x, xticklabels=["D1 alone", "D3 alone", "Together"],
              ylabel="Cooling (K)", ylim=(-.2, .92))
    gains.legend(frameon=False, fontsize=8, loc="upper left")
    for name, color, marker in (("chain", teal, "o"), ("star", rust, "s")):
        curve = data["cases"][name+"_uniform"]["retrospective_wire_curve"]
        caps = [point["cap_m"]*1000 for point in curve]
        vals = [point["best"]["gain_k"] for point in curve]
        wires.step(caps, vals, where="post", lw=1.7, color=color, linestyle="-" if name=="chain" else "--")
        wires.plot(caps, vals, lw=0, marker=marker, markerfacecolor="none", color=color, label=name.capitalize())
    wires.axhline(0, color="#3a4344", lw=.8)
    wires.set(title="Same heat sources, different nets", xticks=[39,52,65,78],
              xlabel="Total pin-distance cap (mm)", ylabel="Best attainable cooling (K)", ylim=(-1.18, .87))
    wires.legend(frameon=False, fontsize=8, loc="lower right")
    for ax in (gains, wires):
        ax.grid(axis="y", alpha=.17)
        ax.set_axisbelow(True)
        ax.spines[["right", "top"]].set_visible(False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
