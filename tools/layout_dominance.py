"""Reproduce the frozen two-workload study described in docs/layout-dominance.md."""
import argparse
from dataclasses import replace
import hashlib
from itertools import permutations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.dominance import peak_curve, worst_excess
from chiplet_floorplanning.placement.evaluate import sample_legal, thermal_key
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.problem import Problem
from chiplet_floorplanning.placement.thermal import AMBIENT_C, power_layer_responses, solve, thermal_case_data


SEED = 20261119
TOL_K = 1e-6
SWEEP = np.linspace(0, 1, 1001)


def passive_control():
    curves = []
    networks = []
    for diagonal, mutual in [(2., 1.4), (2.1, .2)]:
        resistance = np.array([[diagonal, mutual], [mutual, diagonal]])
        conductance = np.linalg.inv(resistance)
        to_ambient = conductance.sum(axis=1)
        assert np.all(to_ambient > 0) and conductance[0, 1] < 0
        rises = np.linalg.solve(conductance, np.eye(2))
        np.testing.assert_allclose(to_ambient @ rises, [1, 1])
        curves.append(peak_curve(*rises.T))
        networks.append(dict(to_ambient_w_k=to_ambient.tolist(), between_nodes_w_k=-conductance[0, 1]))
    excess, weight = worst_excess(*curves)
    ends = (curves[0].at([0, 1]) - curves[1].at([0, 1])).tolist()
    np.testing.assert_allclose([*ends, excess, weight], [-.1, -.1, .55, .5])
    return dict(networks=networks, endpoint_excess_k=ends, worst_excess_k=excess, weight=weight)


def generate(problem):
    rng = np.random.default_rng(SEED)
    layouts, seen = {}, set()
    failed = duplicates = 0
    for _ in range(30):
        try:
            layout = sample_legal(problem, 0, rng)
        except RuntimeError:
            failed += 1
            continue
        key = thermal_key(problem, layout)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        layouts[len(layouts)] = layout
        if len(layouts) == 6:
            break
    return layouts, dict(failed_calls=failed, duplicates=duplicates)


def workload(problem):
    dies = np.argsort(-problem.power_w, kind="stable")[:2]
    powers = np.tile(.25 * problem.power_w, (2, 1))
    powers[np.arange(2), dies] += .75 * min(problem.power_w[dies])
    np.testing.assert_allclose(*powers.sum(axis=1))
    assert np.all((powers >= 0) & (powers <= problem.power_w))
    return powers, [problem.names[i] for i in dies]


def layout_curve(problem, layout, powers, grid, scan=False):
    fields, _ = power_layer_responses(problem, layout, 0, powers, grid)
    temps = fields + AMBIENT_C
    curve = peak_curve(*temps)
    if not scan:
        return curve
    first, second = temps[:, np.isfinite(temps[0])]
    slope = second - first
    # Independent sweep over every cell, bypassing all upper-envelope routines.
    peaks = np.array([np.max(first + w * slope) for w in SWEEP])
    np.testing.assert_allclose(peaks, curve.at(SWEEP), atol=1e-9, rtol=0)
    return curve, peaks, float(np.max(np.abs(slope)))


def compare(candidate, baseline):
    worst, weight = worst_excess(candidate, baseline)
    ends = candidate.at([0, 1]) - baseline.at([0, 1])
    return dict(endpoint_excess_k=ends.tolist(), worst_excess_k=worst, weight=weight,
                missed_k=float(worst - max(ends)),
                peak_c_at_worst=[float(curve.at(weight)) for curve in (candidate, baseline)])


def save_curve(curve):
    return dict(weights=curve.weights.tolist(), peak_c=curve.temperatures.tolist())


def plot_witness(row, path):
    import matplotlib.pyplot as plt

    a, b = row["curves"]
    weights = np.union1d(a["weights"], b["weights"])
    delta = np.interp(weights, a["weights"], a["peak_c"]) - np.interp(weights, b["weights"], b["peak_c"])
    fig, (peaks, diff) = plt.subplots(2, 1, figsize=(7.2, 5.8), sharex=True,
                                      gridspec_kw={"height_ratios": [1.5, 1]}, layout="constrained")
    for curve, label, color in [(a, "A", "#ad502c"), (b, "B", "#196988")]:
        peaks.plot(np.array(curve["weights"]) * 100, curve["peak_c"], color=color,
                   label=f"Layout {label}", linewidth=2)
    peaks.set_title(f'{row["case"]} | Peak temperature under a steady workload mixture', loc="left")
    peaks.set_ylabel("Peak (°C)")
    peaks.legend(frameon=False)
    diff.plot(weights * 100, delta, color="#393852", linewidth=2)
    diff.axhline(0, color="grey", linewidth=.9)
    diff.scatter(100 * row["weight"], row["worst_excess_k"], color="#ad502c", zorder=3)
    diff.annotate(f'{row["worst_excess_k"]:+.2f} K', (100 * row["weight"], row["worst_excess_k"]),
                  xytext=(8, -10), textcoords="offset points")
    diff.set(xlabel="Share of second power map (%)", ylabel="A minus B (K)", xlim=(0, 100))
    for ax in (peaks, diff):
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def direct_check(problem, layouts, powers, grid, row):
    w = row["weight"]
    mixed = replace(problem, power_w=(1 - w) * powers[0] + w * powers[1])
    peaks, balances = [], []
    for idx in [row["candidate"], row["baseline"]]:
        summary, _, _ = solve(thermal_case_data(mixed, layouts[idx], 0, grid))
        peaks.append(summary["peak_power_layer_c"])
        balances.append(summary["energy_balance_error_w"])
    np.testing.assert_allclose(peaks, row["peak_c_at_worst"], rtol=0, atol=1e-5)
    return dict(peaks_c=peaks, energy_balance_errors_w=balances)


def run_case(path):
    raw = path.read_bytes()
    problem = Problem.from_imported(json.loads(raw))
    layouts, sampling = generate(problem)
    info = dict(case=path.stem, input_sha256=hashlib.sha256(raw).hexdigest(), dies=problem.count,
                sampling=sampling, generated=len(layouts))
    if len(layouts) < 6:
        return {**info, "status": "incomplete geometry sample"}, None
    lengths = {i: float(pin_manhattan_um(problem, layout).sum()/1e6) for i, layout in layouts.items()}
    cap = sorted(lengths.values())[4]
    powers, hot = workload(problem)
    feasible = [i for i in layouts if lengths[i] <= cap]
    curves, scans, slopes = {}, {}, {}
    for i in feasible:
        curves[i], scans[i], slopes[i] = layout_curve(problem, layouts[i], powers, 48, scan=True)
    pairs = []
    for i, j in permutations(feasible, 2):
        row = compare(curves[i], curves[j])
        scanned = float(np.max(scans[i] - scans[j]))
        gap = row["worst_excess_k"] - scanned
        # Nearest sweep weight is at most half a grid interval from the maximizer.
        assert -1e-8 <= gap <= (slopes[i] + slopes[j]) / 2000 + 1e-8
        pairs.append(dict(candidate=i, baseline=j, sweep_max_k=scanned, **row))
    admitted = [r for r in pairs if max(r["endpoint_excess_k"]) <= TOL_K]
    witness = max(admitted or pairs, key=lambda r: r["missed_k"])
    witness = {**witness, "direct": direct_check(problem, layouts, powers, 48, witness)}
    candidates = []
    for i in feasible:
        rows = [r for r in pairs if r["candidate"] == i]
        candidates.append(dict(layout=i, length_m=lengths[i], checks=len(curves[i].weights), curve=save_curve(curves[i]),
                               endpoint_regret_k=max([0.] + [max(r["endpoint_excess_k"]) for r in rows]),
                               exact_regret_k=max([0.] + [r["worst_excess_k"] for r in rows])))
    def select(key):
        return min(candidates, key=lambda r: (r[key], r["length_m"], r["layout"]))
    endpoint, exact = select("endpoint_regret_k"), select("exact_regret_k")
    data = dict(status="complete", length_cap_m=cap, hot_dies=hot, power_per_map_w=powers.sum(axis=1).tolist(),
                layouts=[dict(layout=i, centre_um=l.centre_um.tolist(), rotation_deg=l.rotation_deg.tolist(),
                              length_m=lengths[i]) for i, l in layouts.items()],
                candidates=candidates, pairs=pairs, witness=witness, endpoint_choice=endpoint["layout"],
                exact_choice=exact["layout"], decision_gain_k=endpoint["exact_regret_k"]-exact["exact_regret_k"],
                endpoint_admitted=len(admitted), false_replacements=sum(r["worst_excess_k"] > TOL_K for r in admitted),
                false_above_point_one_k=sum(r["worst_excess_k"] > .1 for r in admitted))
    return {**info, **data}, (problem, layouts, powers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="directory of imported Case1.json to Case10.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure", type=Path, help="plot the first prespecified fine-grid witness")
    args = parser.parse_args()
    report = dict(seed=SEED, protocol_commit="83bccad450e61716c8862c3b6cfd3d28dde2a10c",
                  coarse_grid=48, fine_grid=96, passive_control=passive_control(), cases=[], fine=[])
    inputs = {}
    for n in range(1, 11):
        row, inputs[n] = run_case(args.cases / f"Case{n}.json")
        report["cases"].append(row)
        print(row["case"], row["status"], row.get("false_replacements"), row.get("decision_gain_k"), flush=True)
    ranked = sorted((n for n in inputs if inputs[n] is not None),
                    key=lambda n: -report["cases"][n-1]["witness"]["missed_k"])
    for n in ranked[:2]:
        problem, layouts, powers = inputs[n]
        coarse = report["cases"][n-1]["witness"]
        i, j = coarse["candidate"], coarse["baseline"]
        curves = [layout_curve(problem, layouts[k], powers, 96) for k in (i, j)]
        fine = dict(case=f"Case{n}", candidate=i, baseline=j, curves=[save_curve(c) for c in curves], **compare(*curves))
        fine["direct"] = direct_check(problem, layouts, powers, 96, fine)
        report["fine"].append(fine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.figure and report["fine"]:
        plot_witness(report["fine"][0], args.figure)


if __name__ == "__main__":
    main()
