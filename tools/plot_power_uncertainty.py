"""Plot and independently count decisions from the frozen DC and held-out AC evidence."""

import argparse
from collections import Counter
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np

from power_uncertainty import text_digest


STATES = ("certified", "unresolved", "conflict")
COLORS = ("#327a6f", "#e7e5e1", "#b95b42")
LABELS = ("One layout certified", "DC inconclusive", "Conflict proved")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--challenge", type=Path, required=True)
    ap.add_argument("--figure", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--selective", type=Path, help="Check a local replay limited to groups left unresolved")
    args = ap.parse_args()
    predicted = json.loads(args.predictions.read_bytes())
    challenge = json.loads(args.challenge.read_bytes())
    assert challenge["prediction_sha256"] == text_digest(args.predictions)
    matrix, names, counts = [], [], Counter()
    records = []
    for case, observed in zip(predicted["cases"], challenge["cases"], strict=True):
        assert case["name"] == observed["name"]
        row = []
        for boundary in ("nominal", "half_top"):
            forecasts, tests = case["conditions"][boundary], observed["conditions"][boundary]
            for p, t in zip(forecasts["groups"], tests["groups"], strict=True):
                assert (p["budget"], p["fraction"], p["pool"]) == (t["budget"], t["fraction"], t["pool"])
                row.append(STATES.index(p["status"]))
                counts[p["status"]] += 1
                # Recompute the held-out loss from every layout, with one oracle per waveform.
                temperatures = np.array([list(tests["rows"][g]["levels"][str(t["fraction"])].values())
                                         for g in t["pool"]])
                loss = (temperatures - temperatures.min(axis=0)).max(axis=1)
                np.testing.assert_allclose(loss[t["pool"].index(p["chosen"])], t["locked_loss_k"], atol=1e-9)
                np.testing.assert_allclose(loss.min(), t["sample_minimax_k"], atol=1e-9)
                if p["status"] == "certified":
                    assert t["locked_loss_k"] <= predicted["tolerance_k"] + 1e-8
                # A different witness may defeat each layout. Combine losses before minimizing.
                lower = np.maximum(loss, [p["designs"][g]["lower_k"] for g in p["pool"]])
                combined = float(lower.min())
                assert combined <= p["upper_k"] + 1e-8
                after = "conflict" if combined > predicted["tolerance_k"] + 1e-8 else p["status"]
                possible = [case["costs"][g] for g, v in zip(p["pool"], lower)
                            if v <= predicted["tolerance_k"] + 1e-8]
                proven = [case["costs"][g] for g in p["pool"] if p["designs"][g]["upper_k"] <= predicted["tolerance_k"]]
                records.append(dict(case=case["name"], family=case["family"], cooling=boundary, budget=p["budget"],
                                    fraction=p["fraction"], prediction=p["status"], after_challenge=after,
                                    combined_lower_k=combined, locked_loss_k=t["locked_loss_k"],
                                    shortest_sample_cost=t["shortest_cost"], cost_metric=case["cost_metric"],
                                    robust_cost_lower=min(possible, default=None), robust_cost_upper=min(proven, default=None)))
        row_name = case["name"]
        matrix.append(row)
        names.append(row_name)
    print(dict(counts))
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(prediction_sha256=text_digest(args.predictions), challenge_sha256=text_digest(args.challenge),
                   counts_before=counts, counts_after=Counter(r["after_challenge"] for r in records), groups=records)
    if args.selective:
        sparse = json.loads(args.selective.read_bytes())
        assert sparse["unresolved_only"] and sparse["prediction_sha256"] == summary["prediction_sha256"]
        n_all, n_used = 0, 0
        for p, full, reduced in zip(predicted["cases"], challenge["cases"], sparse["cases"], strict=True):
            assert p["name"] == full["name"] == reduced["name"]
            for b, item in full["conditions"].items():
                part = reduced["conditions"][b]
                expected = [q for g, q in zip(p["conditions"][b]["groups"], item["groups"], strict=True)
                            if g["status"] == "unresolved"]
                needed = {g for q in expected for g in q["pool"]}
                assert part["groups"] == expected and needed == set(part["rows"])
                assert all(part["rows"][g] == item["rows"][g] for g in needed)
                n_all += len(item["rows"]) * len(challenge["periods_s"])
                n_used += len(needed) * len(challenge["periods_s"])
        summary["selective_replay"] = dict(full_frequency_factorizations=n_all, used_frequency_factorizations=n_used,
                                           checked_groups=counts["unresolved"], sha256=text_digest(args.selective))
    args.summary.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    fig, ax = plt.subplots(figsize=(8.4, 6.6))
    ax.imshow(matrix, cmap=ListedColormap(COLORS), vmin=-.5, vmax=2.5, aspect="auto", interpolation="nearest")
    ax.set_yticks(range(len(names)), names)
    ax.set_xticks(range(8), ["Wide\n25%", "Wide\n100%", "Tight\n25%", "Tight\n100%"] * 2)
    for i in range(len(names) + 1):
        ax.axhline(i - .5, color="white", lw=2)
    for i in range(9):
        ax.axvline(i - .5, color="white", lw=3 if i % 2 == 0 else 1)
    ax.axhline(9.5, color="#37464b", lw=1.3)
    for x, title in ((.25, "Nominal top cooling"), (.75, "Half top convection")):
        ax.text(x, 1.025, title, ha="center", va="bottom", transform=ax.transAxes, fontsize=12)
    ax.set_xlabel("Interconnect budget and permitted per-die power excursion", labelpad=10)
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.legend(handles=[Patch(color=c, label=s) for c, s in zip(COLORS, LABELS)],
               ncol=3, loc="lower center", frameon=False)
    fig.tight_layout(rect=(0, .065, 1, 1))
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.figure, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
