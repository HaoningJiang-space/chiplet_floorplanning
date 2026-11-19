"""Rank legal geometries under a fixed two-site activity trace and pin-distance cap."""

import argparse
import json
from pathlib import Path

from chiplet_floorplanning.placement import Problem
from cut_traffic import EVIDENCE
from thermal_role_transfer import compare, inputs


def summarize(rows):
    def choose(key):
        return min(rows, key=lambda row: (row[key], row["layout"]))

    best = choose("peak_c")
    selected = choose("self_score_c")
    competitors = [row["lower_c"] for row in rows if row is not selected]
    choices = {}
    for criterion in ("length_m", "steady_peak_c", "self_score_c", "peak_c"):
        row = choose(criterion)
        choices[criterion] = dict(
            layout=row["layout"],
            length_m=row["length_m"],
            peak_c=row["peak_c"],
            loss_k=row["peak_c"] - best["peak_c"],
        )
    return dict(
        geometries=rows,
        choices=choices,
        range_k=max(row["peak_c"] for row in rows) - best["peak_c"],
        self_loss_bound_k=max(0.0, selected["upper_c"] - min(competitors, default=float("inf"))),
    )


def evaluate(entry, cases, count, durations, *, grid=32, steps=4):
    source = cases / (entry["case"] + ".json")
    problem = Problem.from_imported(json.loads(source.read_bytes()))
    sites = sorted(range(len(problem.names)), key=lambda i: (-problem.power_w[i], i))[:count]
    for geometry in entry["layouts"]:
        if geometry["length_m"] > entry["length_cap_m"]:
            continue
        meta, model = inputs(entry, source, "nominal", grid, geometry=geometry, fixed_sites=sites)
        for dwell in durations:
            result = compare(meta, model, dwell, steps, replay_all=True)
            for pair in result["peaks"]:
                row = dict(
                    layout=geometry["layout"],
                    length_m=meta["length_m"],
                    steady_peak_c=result["steady_peak_c"],
                    **{k: pair[k] for k in ("peak_c", "lower_c", "upper_c", "self_score_c", "direct")},
                )
                yield meta, (dwell, tuple(pair["pair"])), row


def run(entry, cases, uncertain):
    groups = {}
    count, durations = (4, (0.005, 0.05, 0.5)) if uncertain else (2, (0.005, 0.5))
    for meta, scenario, row in evaluate(entry, cases, count, durations):
        groups.setdefault(scenario, []).append(row)
    common = dict(
        case=entry["case"],
        boundary="nominal",
        grid=32,
        substeps=4,
        budget_m=entry["length_cap_m"],
        sites=meta["site_names"],
        mean_total_w=meta["mean_total_w"],
        amplitude_w=meta["amplitude_w"],
    )
    if not uncertain:
        return [dict(**common, dwell_s=dwell, **summarize(rows)) for (dwell, _), rows in groups.items()]

    records, regrets, bounds, lower_bounds = [], {}, {}, {}
    for (dwell, pair), rows in groups.items():
        scenario = summarize(rows)
        optimum = scenario["choices"]["peak_c"]["peak_c"]
        for row in rows:
            layout = row["layout"]
            regrets.setdefault(layout, []).append(row["peak_c"] - optimum)
            other_lower = min(other["lower_c"] for other in rows if other is not row)
            bounds.setdefault(layout, []).append(max(0.0, row["upper_c"] - other_lower))
            other_upper = min(other["upper_c"] for other in rows if other is not row)
            lower_bounds.setdefault(layout, []).append(max(0.0, row["lower_c"] - other_upper))
        records.append(dict(dwell_s=dwell, pair=pair, **scenario))
    layouts = [
        dict(
            layout=layout,
            worst_regret_k=max(losses),
            worst_bound_k=max(bounds[layout]),
            worst_lower_k=max(lower_bounds[layout]),
            witness=losses.index(max(losses)),
        )
        for layout, losses in regrets.items()
    ]
    fixed = min(layouts, key=lambda row: (row["worst_regret_k"], row["layout"]))
    interval_choice = min(layouts, key=lambda row: (row["worst_bound_k"], row["layout"]))
    assert len({r["choices"]["steady_peak_c"]["layout"] for r in records}) == 1
    return [
        dict(
            **common,
            steady_layout=records[0]["choices"]["steady_peak_c"]["layout"],
            minimax_regret_layout=fixed["layout"],
            interval_layout=interval_choice["layout"],
            minimax_lower_k=min(r["worst_lower_k"] for r in layouts),
            layouts=layouts,
            scenarios=records,
        )
    ]


def refine(screen, cases, entries):
    """Recheck the largest fixed-layout minimax regret and the same pair at a different dwell."""

    def worst_fixed(case):
        return next(r for r in case["layouts"] if r["layout"] == case["minimax_regret_layout"])

    case = max(screen, key=lambda c: worst_fixed(c)["worst_regret_k"])
    witness = case["scenarios"][worst_fixed(case)["witness"]]
    pair = tuple(witness["pair"])
    dwell = witness["dwell_s"]
    other = min(s["dwell_s"] for s in case["scenarios"] if s["dwell_s"] != dwell)
    entry = next(e for e in entries if e["case"] == case["case"])
    grouped = {time: [] for time in (other, dwell)}
    for meta, (time, active), row in evaluate(entry, cases, 4, grouped, grid=64, steps=8):
        if active == pair:
            grouped[time].append(row)
    return [
        dict(
            case=entry["case"],
            sites=meta["site_names"],
            pair=pair,
            budget_m=entry["length_cap_m"],
            dwell_s=time,
            grid=64,
            substeps=8,
            **summarize(rows),
        )
        for time, rows in grouped.items()
    ]


def plot_witness(results, sources, entries, path):
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle
    from chiplet_floorplanning.placement import Layout
    from chiplet_floorplanning.placement.geometry import boxes

    results = sorted(results, key=lambda row: row["dwell_s"])
    sample = results[0]
    entry = next(e for e in entries if e["case"] == sample["case"])
    problem = Problem.from_imported(json.loads((sources / (entry["case"] + ".json")).read_bytes()))
    winners = list(dict.fromkeys(row["choices"]["peak_c"]["layout"] for row in results))
    active = [sample["sites"][i] for i in sample["pair"]]
    figure, panels = plt.subplots(
        1, len(winners) + 1, figsize=(3.25 * (1 + len(winners)), 3.25), layout="constrained"
    )
    for ax, identifier in zip(panels, winners):
        geometry = next(row for row in entry["layouts"] if row["layout"] == identifier)
        layout = Layout(np.array(geometry["centre_um"]), np.array(geometry["rotation_deg"]))
        for name, (x0, y0, x1, y1) in zip(problem.names, boxes(problem, layout) / 1000):
            color = "#ce6950" if name in active else "#d2d9dc"
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color, edgecolor="white", lw=0.7))
            if name in active:
                ax.text(
                    (x0 + x1) / 2, (y0 + y1) / 2, name.split("_")[-1], ha="center", va="center", fontsize=9
                )
        width, height = np.asarray(problem.carrier_um) / 1000
        ax.set(
            xlim=(0, width),
            ylim=(0, height),
            aspect="equal",
            xlabel="x (mm)",
            ylabel="y (mm)",
            title=f"Layout {identifier}  |  {geometry['length_m']:.2f} m",
        )
    ax = panels[-1]
    times = [round(row["dwell_s"] * 1000) for row in results]
    for identifier, color in zip(winners, ("#276b85", "#aa4b35")):
        peaks = [
            next(g["peak_c"] for g in row["geometries"] if g["layout"] == identifier) for row in results
        ]
        ax.plot(times, peaks, "o-", color=color, label=f"Layout {identifier}")
    ax.set(title="Periodic peak", xlabel="Time per task (ms)", ylabel="Peak temperature (°C)", xticks=times)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    figure.suptitle(f"{entry['case']}  |  Opposite power pulses at {' and '.join(active)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=170)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--uncertain-sources", action="store_true", help="design for any pair of the four fixed sites"
    )
    mode.add_argument(
        "--refine", type=Path, help="refine a timing comparison from an uncertain-sources screen"
    )
    parser.add_argument("--figure", type=Path, help="draw the geometries and two refined temperatures")
    args = parser.parse_args()
    if args.figure and not args.refine:
        parser.error("--figure requires --refine")
    cases = json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    if args.refine:
        results = refine(json.loads(args.refine.read_bytes()), args.cases, cases)
    else:
        results = []
        for entry in cases:
            if entry["case"] in ("Case2", "Case3", "Case4", "Case5"):
                results.extend(run(entry, args.cases, args.uncertain_sources))
                print(entry["case"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.figure:
        plot_witness(results, args.cases, cases, args.figure)


if __name__ == "__main__":
    main()
