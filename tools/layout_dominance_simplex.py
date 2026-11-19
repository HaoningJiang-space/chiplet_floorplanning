"""Three-mode and finer-grid follow-up using the same saved layout pools."""
import argparse
from dataclasses import replace
import hashlib
from itertools import combinations, permutations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.dominance import peak_curve, potential_hotspots, simplex_worst_excess, worst_excess
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.thermal import AMBIENT_C, power_layer_responses, solve, thermal_case_data
from layout_dominance import layout_curve, workload


def control():
    matrices = []
    for diag, other in [(2., 1.), (3., .1)]:
        resistance = np.full((3, 3), other) + np.eye(3) * (diag - other)
        g = np.linalg.inv(resistance)
        assert (g.sum(axis=1) > 0).all() and (g[np.triu_indices(3, 1)] < 0).all()
        responses = np.linalg.solve(g, np.eye(3))
        np.testing.assert_allclose(g.sum(axis=1) @ responses, np.ones(3))
        matrices.append(responses)
    edge = max(worst_excess(*(peak_curve(*m[:, [i, j]].T) for m in matrices))[0]
               for i, j in combinations(range(3), 2))
    entire, weights = simplex_worst_excess(*matrices)
    np.testing.assert_allclose([edge, entire], [-.05, 4/15])
    return dict(edge_worst_k=edge, simplex_worst_k=entire, weights=weights.tolist())


def fine_selection(problem, layouts, lengths):
    powers, _ = workload(problem)
    curves = {i: layout_curve(problem, layout, powers, 96) for i, layout in layouts.items()}
    records = []
    for i, a in curves.items():
        end = max(float(max(a.at([0, 1]) - b.at([0, 1]))) for b in curves.values())
        exact = max(worst_excess(a, b)[0] for b in curves.values())
        records.append(dict(layout=i, length_m=lengths[i], endpoint_regret_k=end, exact_regret_k=exact))
    def best(metric):
        return min(records, key=lambda r: (r[metric], r["length_m"], r["layout"]))
    before, after = best("endpoint_regret_k"), best("exact_regret_k")
    return dict(candidates=records, endpoint_choice=before["layout"], exact_choice=after["layout"],
                decision_gain_k=before["exact_regret_k"]-after["exact_regret_k"])


def triangle(problem, layouts):
    picks = np.argsort(-problem.power_w, kind="stable")[:3]
    powers = np.tile(.25 * problem.power_w, (3, 1))
    powers[np.arange(3), picks] += .75 * min(problem.power_w[picks])
    assert (powers <= problem.power_w).all() and np.allclose(powers.sum(1), powers.sum(1)[0])
    sweep = np.array([(i, j, 50-i-j) for i in range(51) for j in range(51-i)]) / 50
    hotspots, edge_curves, scans = {}, {}, {}
    for k, layout in layouts.items():
        fields, _ = power_layer_responses(problem, layout, 0, powers, 48)
        assert np.all(np.isfinite(fields) == np.isfinite(fields[0]))
        cells = fields[:, np.isfinite(fields[0])].T + AMBIENT_C
        hotspots[k] = potential_hotspots(cells)
        edge_curves[k] = [peak_curve(*cells[:, [i, j]].T) for i, j in combinations(range(3), 2)]
        scans[k] = np.array([(cells @ w).max() for w in sweep])
    rows = []
    for i, j in permutations(layouts, 2):
        edge = max(worst_excess(a, b)[0] for a, b in zip(edge_curves[i], edge_curves[j]))
        value, weights = simplex_worst_excess(hotspots[i], hotspots[j])
        at_witness = (hotspots[i] @ weights).max() - (hotspots[j] @ weights).max()
        np.testing.assert_allclose(value, at_witness, atol=1e-7, rtol=0)
        scanned = float(np.max(scans[i] - scans[j]))
        assert value >= max(edge, scanned) - 1e-7
        rows.append(dict(candidate=i, baseline=j, edge_worst_k=edge, simplex_worst_k=value,
                         missed_vs_edge_k=value-edge, sweep_max_k=scanned, weights=weights.tolist()))
    witness = max(rows, key=lambda r: r["missed_vs_edge_k"])
    mixed = replace(problem, power_w=np.asarray(witness["weights"]) @ powers)
    peaks = [solve(thermal_case_data(mixed, layouts[witness[k]], 0, 48))[0]["peak_power_layer_c"]
             for k in ("candidate", "baseline")]
    np.testing.assert_allclose(peaks[0] - peaks[1], witness["simplex_worst_k"], rtol=0, atol=1e-5)
    return dict(hot_dies=[problem.names[i] for i in picks], power_per_map_w=powers.sum(1).tolist(),
                sweep_points=len(sweep), pairs=rows, witness={**witness, "direct_peak_c": peaks})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--two-mode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = dict(protocol_commit="c8bc38c62210edcf1cd12677ba406f6ac9e5207a", control=control(), cases={})
    for case in json.loads(args.two_mode.read_text(encoding="utf-8"))["cases"]:
        name = case["case"]
        if name not in ("Case3", "Case8"):
            continue
        raw = (args.cases / f"{name}.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case["input_sha256"]
        problem = Problem.from_imported(json.loads(raw))
        layouts, lengths = {}, {}
        for r in case["layouts"]:
            i = r["layout"]
            layout = Layout(np.array(r["centre_um"]), np.array(r["rotation_deg"]))
            length = float(pin_manhattan_um(problem, layout).sum() / 1e6)
            if length <= case["length_cap_m"]:
                layouts[i], lengths[i] = layout, length
        assert set(layouts) == {r["layout"] for r in case["candidates"]}
        if name == "Case8":
            report["case8_fine_selection"] = fine_selection(problem, layouts, lengths)
        report["cases"][name] = triangle(problem, layouts)
        print(name, report["cases"][name]["witness"], flush=True)
    assert set(report["cases"]) == {"Case3", "Case8"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
