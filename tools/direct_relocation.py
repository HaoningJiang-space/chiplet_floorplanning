"""Freeze a direct thermal relocation, then score the locked coordinates in the full package."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, is_legal
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.relocation import ConnectionCost, landing_bank, select_landing
from chiplet_floorplanning.placement.thermal import die_peaks_c, solve, thermal_case_data
from cut_traffic import EVIDENCE
from power_uncertainty import cases, text_digest


SEED = 20261119
PROTOCOL = "a534a297df8879270af345b48ac33e87500c0de4"


def rules(problem, meta):
    if meta["family"] == "ATPlace":
        return problem, None
    plan = json.loads((EVIDENCE / "tap-sensitivity-plan.json").read_bytes())
    domain = next(e["domain"] for e in plan["cases"] if e["domain"]["name"] == problem.name)
    ring = [c["bump_ring_um"] for c in sorted(domain["chiplets"], key=lambda c: c["id"])]
    return replace(problem, size_um=problem.size_um + 2*np.array(ring)[:, None]), np.array(domain["connection_wire_demands"])


def physical_cost(problem, layout, demand):
    if demand is None:
        return float(pin_manhattan_um(problem, layout).sum()/1e6)
    xy = layout.centre_um
    return float(np.sum(demand * abs(xy[:, None] - xy).sum(axis=2)) / (1000*demand.sum()))


def opposite(points, chosen, layout):
    if not chosen.chips:
        return None
    chip = chosen.chips[0]
    direction = chosen.destinations_um[0] - layout.centre_um[chip]
    size = np.linalg.norm(direction)
    choices = []
    for p in points:
        if chip in p.chips:
            delta = p.destinations_um[p.chips.index(chip)] - layout.centre_um[chip]
            if delta @ direction < 0:
                choices.append(((len(p.chips) != len(chosen.chips), abs(np.linalg.norm(delta) - size), p.cost), p))
    return min(choices, key=lambda x: x[0])[1] if choices else None


def record(point, start, problem, field):
    if point is None:
        return None
    final = point.apply(start)
    rises = field.rises(final.centre_um)
    assert abs(float(rises.max()) - point.rise_k) < 1e-8
    return dict(chips=[problem.names[k] for k in point.chips], indices=point.chips,
                from_um=start.centre_um[list(point.chips)].tolist(), to_um=point.destinations_um,
                cost=point.cost, predicted_rise_k=point.rise_k, predicted_hot=problem.names[int(rises.argmax())])


def predict(problem, designs, meta):
    index, start, start_cost = min(designs, key=lambda x: x[0])
    footprint, demand = rules(problem, meta)
    costs = ConnectionCost(problem, start, demand)
    assert abs(start_cost - costs.initial) < 1e-9
    bank, field = landing_bank(problem, footprint, start, costs)
    hottest = int(field.initial.argmax())
    limits = {"strict": start_cost, "published": meta["wide_cap"]}
    groups = {}
    for name, cap in limits.items():
        eligible = [p for p in bank[1:] if p.cost <= cap + 1e-9]
        direct = select_landing(bank, cap)
        rng = np.random.default_rng(SEED)
        choices = dict(direct=direct, hottest=select_landing(bank, cap, movable=hottest),
                       random=eligible[int(rng.integers(len(eligible)))] if eligible else bank[0],
                       shortest=min([bank[0], *eligible], key=lambda p: p.cost),
                       opposite=opposite(eligible, direct, start))
        for p in choices.values():
            if p is not None:
                final = p.apply(start)
                exact = physical_cost(problem, final, demand)
                assert is_legal(footprint, final, 100) and abs(exact - p.cost) < 1e-9 and exact <= cap + 1e-9
        groups[name] = dict(cap=cap, possible_translations=sum(len(p.chips) == 1 for p in eligible),
                            possible_exchanges=sum(len(p.chips) == 2 for p in eligible),
                            choices={k: record(p, start, problem, field) for k, p in choices.items()})
    return dict(**meta, anchor_id=index, anchor_xy_um=start.centre_um.tolist(), rotation_deg=start.rotation_deg.tolist(),
                start=record(bank[0], start, problem, field), chip_names=problem.names, rated_w=problem.power_w.tolist(),
                predicted_hot=problem.names[hottest], groups=groups)


def rebuild(start, action):
    xy = start.centre_um.copy()
    for k, old, new in zip(action["indices"], action["from_um"], action["to_um"], strict=True):
        np.testing.assert_array_equal(xy[k], old)
        xy[k] = new
    return Layout(xy, start.rotation_deg.copy())


def package_score(problem, layout, grid):
    data = thermal_case_data(problem, layout, 100, resolution=grid)
    summary, rise, edges = solve(data, node_limit=450000)
    die = die_peaks_c(problem, layout, rise, edges)
    return dict(peak_c=summary["peak_power_layer_c"], hottest_die=problem.names[int(die.argmax())],
                die_peak_c=die.tolist(), heat_w=summary["source_power_w"], removed_w=summary["heat_removed_w"],
                residual_w=summary["linear_residual_inf_w"])


def score_case(problem, designs, meta, frozen, grid, *, only=None):
    idx, start, _ = min(designs, key=lambda x: x[0])
    assert meta["bank_sha256"] == frozen["bank_sha256"] and idx == frozen["anchor_id"]
    np.testing.assert_array_equal(start.centre_um, frozen["anchor_xy_um"])
    np.testing.assert_array_equal(start.rotation_deg, frozen["rotation_deg"])
    footprint, demand = rules(problem, meta)
    cache = {}

    def evaluate(a, cap):
        final = rebuild(start, a)
        cost = physical_cost(problem, final, demand)
        assert is_legal(footprint, final, 100) and abs(a["cost"] - cost) < 1e-9 and cost <= cap + 1e-9
        key = final.centre_um.tobytes()
        if key not in cache:
            cache[key] = package_score(problem, final, grid)
        return dict(cost=cost, **cache[key])

    start_score = evaluate(frozen["start"], frozen["start"]["cost"])
    groups = {}
    for cap_name, group in frozen["groups"].items():
        if only is not None and cap_name not in only:
            continue
        cap = group["cap"]
        choices = {}
        for arm, action in group["choices"].items():
            if action is None or (only is not None and arm != "direct"):
                continue
            result = evaluate(action, cap)
            choices[arm] = dict(**result, cooling_k=start_score["peak_c"] - result["peak_c"])
        hits = [k for k, v in choices.items() if v["cooling_k"] >= .1]
        shortest = min(hits, key=lambda k: choices[k]["cost"], default=None)
        groups[cap_name] = dict(choices=choices, shortest_at_cooling_target=shortest)
    return dict(name=meta["name"], family=meta["family"], start=start_score, groups=groups, distinct_solves=len(cache))


def mirrored_sink():
    # Solve the same 1-D finite-volume conductor twice, reversing only the anchored-temperature end.
    # One passive I/O chip at x=5 in a parallel row gives equal connection costs to x=3 and 7.
    conductance_w_k = 1.0
    results = {}
    for sink in (0, 10):
        g = np.diag([1., *([2.] * 9), 1.]) - np.diag(np.ones(10), 1) - np.diag(np.ones(10), -1)
        free = np.arange(11) != sink
        peaks = []
        for chip in (3, 5, 7):
            power = np.eye(11)[chip]  # 1 W
            rise = np.linalg.solve(conductance_w_k * g[np.ix_(free, free)], power[free])
            assert abs(rise.max() - abs(chip - sink)/conductance_w_k) < 1e-10
            peaks.append(float(rise.max()))
        results[str(sink)] = peaks
    return dict(node_pitch_mm=1, positions_mm=[3, 5, 7], power_w=1, edge_conductance_w_k=conductance_w_k,
                io_xy_mm=[5, 1], source_y_mm=0, pin_distances_mm=[3, 1, 3], cap_mm=3, peak_rise_k=results)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--audit", type=Path, help="Evaluate a previously locked set of moves")
    args = ap.parse_args()
    entries = list(cases(args.cases))
    report = dict(protocol=PROTOCOL, seed=SEED, cases=[])
    if args.audit:
        pred = json.loads(args.audit.read_bytes())
        assert pred["protocol"] == PROTOCOL
        report.update(predictions_sha256=text_digest(args.audit), grid=64, refinement_grid=96,
                      mirrored_sink=mirrored_sink(), refinement=[])
        for entry, locked in zip(entries, pred["cases"], strict=True):
            report["cases"].append(score_case(*entry, locked, 64))
            print(entry[2]["name"], flush=True)
        for family in ("ATPlace", "TAP-2.5D"):
            rows = [(q["choices"]["direct"]["cooling_k"], i, b) for i, r in enumerate(report["cases"])
                    if r["family"] == family for b, q in r["groups"].items()]
            targeted = [max(rows, key=lambda x: x[0])]
            if min(v[0] for v in rows) < -1e-9:
                targeted.append(min(rows, key=lambda x: x[0]))
            for _, i, b in targeted:
                report["refinement"].append(score_case(*entries[i], pred["cases"][i], 96, only=[b]))
    else:
        for entry in entries:
            report["cases"].append(predict(*entry))
            print(entry[2]["name"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
