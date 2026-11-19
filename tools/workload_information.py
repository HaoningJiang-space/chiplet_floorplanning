"""Test which design-time workload descriptions preserve a common floorplan."""

import argparse
import json
from collections import defaultdict
from itertools import pairwise
from math import sqrt, tanh
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.decision import worst_regret_bounds
from cut_traffic import EVIDENCE, digest, traffic_sweep
from thermal_geometry_transfer import evaluate


TOLERANCE_K = 0.1
DESCRIPTIONS = {"mean": (), "pair": ("pair",), "dwell": ("dwell_s",), "both": ("pair", "dwell_s")}


def storage_control():
    """An analytic control: agreement on three time samples can miss a reversal."""
    durations = sorted([0.005, 0.05, 0.5, sqrt(0.005 * 0.05), sqrt(0.05 * 0.5)])
    rows = []
    for time in durations:
        # Two sites at 5.00 and 5.65 K mean rise; an always-cool reference
        # balances total power. R=1 K/W and the alternating amplitude is 1 W.
        pulse_a = max(5 + tanh(time / 0.01), 5.65)
        pulse_b = max(5, 5.65 + tanh(time / 0.1))
        rows.append(
            dict(dwell_s=time, peak_a_k=pulse_a, peak_b_k=pulse_b, loss_a_k=max(0.0, pulse_a - pulse_b))
        )
    return rows


def ring_information():
    """Apply the same decision test to throughput of the four-terminal symmetric ring."""
    reference = traffic_sweep()
    grid = round(1 / reference["share_step"])
    scale = 4 * reference["raw_gbps_per_directed_edge"] * reference["payload_fraction"] / 8000
    groups = {name: defaultdict(list) for name in ("total", "unlabelled_shares", "lightest_matching")}
    for i in range(grid + 1):
        for j in range(grid - i + 1):
            counts = (i, j, grid - i - j)
            rates = [scale * grid / (counts[d] + max(counts[k] for k in range(3) if k != d))
                     for d in range(3)]
            # Minimizing negative throughput expresses regret in lost TB/s.
            loss = [-rate for rate in rates]
            groups["total"][()].append(loss)
            groups["unlabelled_shares"][tuple(sorted(counts))].append(loss)
            groups["lightest_matching"][int(np.argmin(counts))].append(loss)
    summary = {}
    for name, partition in groups.items():
        worst = max(worst_regret_bounds(cost, cost)[1].min() for cost in partition.values())
        summary[name] = dict(groups=len(partition), worst_loss_TB_s=float(worst))
    return dict(descriptions=summary, independent_flow_sweep=reference)


def group_results(scenarios):
    layouts = sorted(row["layout"] for row in scenarios[0]["geometries"])
    tables = [sorted(s["geometries"], key=lambda row: row["layout"]) for s in scenarios]
    assert all([r["layout"] for r in table] == layouts for table in tables)

    def matrix(field):
        return np.array([[r[field] for r in table] for table in tables])

    lower, upper = worst_regret_bounds(matrix("lower_c"), matrix("upper_c"))
    exact, _ = worst_regret_bounds(matrix("peak_c"), matrix("peak_c"))
    assert np.all(lower <= exact + 1e-8) and np.all(exact <= upper + 1e-8)
    chosen = int(upper.argmin())
    return dict(
        interval_choice=layouts[chosen],
        common_designs=[g for g, v in zip(layouts, exact) if v <= TOLERANCE_K],
        certified_designs=[g for g, v in zip(layouts, upper) if v <= TOLERANCE_K],
        minimax_k=float(exact.min()),
        selected_loss_k=float(exact[chosen]),
        lower_k=float(lower.min()),
        upper_k=float(upper[chosen]),
    )


def partitions(scenarios, fields):
    groups = defaultdict(list)
    for scenario in scenarios:
        key = tuple(tuple(scenario[f]) if f == "pair" else scenario[f] for f in fields)
        groups[key].append(scenario)
    return [dict(description=dict(zip(fields, key)), **group_results(rows)) for key, rows in groups.items()]


def trial(case, entry, sources):
    scenarios = case["scenarios"]
    fit = {name: partitions(scenarios, fields) for name, fields in DESCRIPTIONS.items()}
    frozen = {tuple(row["description"]["pair"]): row for row in fit["pair"]}
    trained = sorted({s["dwell_s"] for s in scenarios})
    new_dwells = [sqrt(a * b) for a, b in pairwise(trained)]
    holdout = defaultdict(list)
    for _, (time, pair), row in evaluate(entry, sources, count=4, durations=new_dwells):
        holdout[time, pair].append(row)

    transfer = []
    for (time, pair), rows in holdout.items():
        group = frozen[pair]
        chosen = next(r for r in rows if r["layout"] == group["interval_choice"])
        oracle = min(r["peak_c"] for r in rows)
        certified = group["upper_k"] <= TOLERANCE_K
        rivals = [r["lower_c"] for r in rows if r is not chosen]
        bound = max(0.0, chosen["upper_c"] - min(rivals))
        transfer.append(
            dict(
                pair=pair,
                dwell_s=time,
                committed=certified,
                layout=chosen["layout"],
                loss_k=chosen["peak_c"] - oracle,
                upper_k=bound,
                geometries=rows,
            )
        )
    return dict(case=case["case"], fit=fit, holdout=transfer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prior = EVIDENCE / "thermal-rule-transfer" / "uncertain.json"
    anchors = json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())
    entries = {entry["case"]: entry for entry in anchors["cases"]}
    cases = [trial(case, entries[case["case"]], args.cases) for case in json.loads(prior.read_bytes())]
    evidence = dict(
        protocol="7e3dd39d7761f48f6470b8876926baed5e2c884d",
        seed=anchors["seed"],
        training_sha256=digest(prior),
        tolerance_k=TOLERANCE_K,
        cases=cases,
        analytic_storage_control=storage_control(),
        ring=ring_information(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
