"""Collect fixed-budget placement decisions and plot a success and a missed hotspot."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement.geometry import boxes
from common_relocation import FOUR, TARGET
from power_uncertainty import cases, text_digest


def plot(inputs, trials, path):
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.6), layout="constrained")
    examples = {"Case2": (axes[0], "adaptive"), "micro150": (axes[1], "three")}
    for p, designs, _ in cases(inputs):
        if p.name not in examples:
            continue
        ax, method = examples[p.name]
        row = trials[p.name]
        action = row["candidates"][row["methods"][method]["selected"]]
        _, start, _ = min(designs, key=lambda t: t[0])
        bounds = boxes(p, start)/1000
        for x, y, u, v in bounds:
            ax.add_patch(Rectangle((x, y), u-x, v-y, fc="#e4e8ea", ec="#8c999f", lw=.8))
        for chip, dest, color in zip(action["indices"], action["to_um"], ("#256393", "#19836e")):
            x, y, u, v = bounds[chip]
            old, new = start.centre_um[chip]/1000, np.asarray(dest)/1000
            ax.add_patch(Rectangle((x, y), u-x, v-y, fc=color, ec=color, alpha=.45))
            ax.add_patch(Rectangle(np.array([x, y])+new-old, u-x, v-y, fill=False, ec=color, lw=1.8, ls="--"))
            ax.annotate("", new, old, arrowprops=dict(arrowstyle="-|>", lw=1.7, color=color))
            ax.plot([], [], lw=2, c=color, label=p.names[chip])
        if method == "three":
            # Convert [row, column] in the sheet to micrometre-carrier coordinates in mm.
            carrier = np.array(p.carrier_um)/1000
            side = max(100., max(carrier)+20)
            origin = (carrier-side)/2
            b = action["worst"]["boundary"]
            points = np.array(row["observers_yx"][b])[:, ::-1]+.5+origin
            hot = np.array(action["worst"]["cell_yx"])[::-1]+.5+origin
            ax.scatter(*points.T, marker="o", facecolors="white", edgecolors="#5a373b", s=38, label="Old probes")
            ax.scatter(*hot, marker="*", color="#b72e37", s=140, label="New peak", zorder=5)
        title = "Case2  |  Verified joint move" if method == "adaptive" else "micro150  |  Fixed probes miss the new peak"
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax.set(xlim=(0, p.carrier_um[0]/1000), ylim=(0, p.carrier_um[1]/1000),
               aspect="equal", xlabel="Carrier x (mm)", ylabel="Carrier y (mm)")
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.15), ncol=2, frameon=False, fontsize=9)
    fig.savefig(path, dpi=165, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--evidence", required=True, type=Path)
    args = ap.parse_args()
    d = args.evidence
    def load(name):
        return json.loads((d / (name+".json")).read_bytes())
    trial, package, landing, alternate = map(load, ("selection", "package", "landings", "landing-package"))
    h = text_digest(d/"selection.json")
    assert package["selection_sha256"] == landing["bank_sha256"] == alternate["bank_sha256"] == h
    assert alternate["prediction_sha256"] == text_digest(d/"landings.json")
    details, aggregate = {}, {}
    for name, case in trial["cases"].items():
        reference = case["methods"]["full"]
        details[name] = {}
        for arm, v in (case["methods"] | landing["cases"][name]["methods"]).items():
            k = v["selected"]
            selected = str(k)
            worst, centre = 0., 0.
            if k:
                data = package["cases"][name]["conditions"]
                if selected not in data["west"]:
                    data = alternate["cases"][name]["conditions"]
                worst = min(data[b][selected]["cooling_k"] for b in FOUR)
                centre = data["centre"][selected]["cooling_k"]
            details[name][arm] = dict(index=k, gain_k=v["actual_gain_k"], peak_loss_k=v["regret_k"],
                                      package_four_k=worst, package_centre_k=centre,
                                      same_landing=k == reference["selected"])
            tally = aggregate.setdefault(arm, dict(same_landing=0, peak_losses=0, max_loss_k=0.,
                false_accepts=0, package_four_pass=0, package_five_pass=0, fields=0, extra_adjoints=0,
                scoring_seconds=0.))
            tally["same_landing"] += int(k == reference["selected"])
            tally["peak_losses"] += int(v["regret_k"] > 1e-8)
            tally["max_loss_k"] = max(tally["max_loss_k"], v["regret_k"])
            tally["false_accepts"] += int(bool(k) and v["actual_gain_k"] <= TARGET)
            tally["package_four_pass"] += int(worst > TARGET)
            tally["package_five_pass"] += int(min(worst, centre) > TARGET)
            tally["fields"] += v["candidate_fields"]
            tally["extra_adjoints"] += v["extra_adjoints"]
            tally["scoring_seconds"] += v["scoring_seconds"]
    summary = dict(bank_sha256=h, common_seconds=sum(r["common_seconds"] for r in trial["cases"].values()),
                   paired_cases=len(details), methods=aggregate, cases=details)
    (d/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8", newline="\n")
    plot(args.cases, trial["cases"], d/"joint-landings.png")


if __name__ == "__main__":
    main()
