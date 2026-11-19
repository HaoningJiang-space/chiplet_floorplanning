"""Generate physical layouts for two conflicting dwell times under one pin-distance cap."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import material_grids
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.decision import ThermalCandidate, search_thermal_targets
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.lp import hotspot_move, legalize_relations
from chiplet_floorplanning.placement.search import layout_key
from chiplet_floorplanning.placement.thermal import thermal_case_data
from cut_traffic import EVIDENCE, digest
from periodic_layout_choice import replay
from thermal_role_transfer import alternating_fields, inputs


GAP_UM = 100
SEED = 20261119
DWELLS = (0.005, 0.05)
MIDPOINT = float(np.sqrt(np.prod(DWELLS)))
PAIRS = {"Case4": (1, 3), "Case5": (0, 3)}


def geometry(problem, layout):
    return dict(centre_um=layout.centre_um.tolist(), rotation_deg=layout.rotation_deg.tolist(),
                length_m=float(pin_manhattan_um(problem, layout).sum() / 1e6))


def measure(problem, entry, source, sites, layout, dwells, grid, steps, *, audit=False):
    assert is_legal(problem, layout, GAP_UM)
    record = geometry(problem, layout)
    meta, model = inputs(entry, source, "nominal", grid, geometry=dict(layout="candidate", **record),
                         fixed_sites=sites)
    g, capacity, mean, unit, sink, nodes, ambient, steady = model
    i, j = PAIRS[entry["case"]]
    delta = meta["amplitude_w"] * (unit[:, i] - unit[:, j])
    power = np.column_stack((mean + delta, mean - delta))
    assert power.min() >= -1e-10
    np.testing.assert_allclose(power.sum(axis=0), meta["mean_total_w"], atol=1e-7, rtol=0)
    case = parse_case(thermal_case_data(problem, layout, GAP_UM, grid), node_limit=450000)
    assert tuple(d.id for d in case.dies) == problem.names
    owner, masks, _, _ = material_grids(case)
    z = next(k for k, layer in enumerate(case.thermal["layers"]) if layer["id"] == case.thermal["power_layer"])
    dies = owner[masks[z]]
    active = dies >= 0
    peaks, die_peaks, checks = [], [], []
    for dwell in dwells:
        phases = alternating_fields(g, capacity, delta[:, None], dwell, steps)[:, :, 0]
        spatial = ambient + steady[nodes] + phases[:, nodes].max(axis=0)
        peak = float(spatial.max())
        per_die = np.full(problem.count, -np.inf)
        np.maximum.at(per_die, dies[active], spatial[active])
        assert np.isfinite(per_die).all()
        peaks.append(peak)
        die_peaks.append(per_die)
        if audit:
            check = replay(g, capacity, power, sink, steady + phases[-1], "01", dwell, steps, nodes, ambient)
            check["peak_difference_k"] = abs(check["direct_peak_c"] - peak)
            assert check["peak_difference_k"] < 1e-6
            checks.append(check)
    return ThermalCandidate(layout, record["length_m"], np.array(peaks), np.array(die_peaks)), checks


def compare_pools(rows, anchors, arms):
    """All returned-design comparisons use the same fine-grid oracle, including the holdout."""
    old = np.min([rows[name]["peaks_c"] for name in anchors], axis=0)
    oracle = np.min([r["peaks_c"] for r in rows.values()], axis=0)

    def point(name):
        r = rows[name]
        regret = np.array(r["peaks_c"]) - oracle
        return dict(layout=name, peaks_c=r["peaks_c"], length_m=r["length_m"],
                    worst_loss_k=float(regret[:2].max()), midpoint_loss_k=float(regret[2]))

    def group(names):
        scores = [point(name) for name in dict.fromkeys(names)]
        best = min(scores, key=lambda s: (s["worst_loss_k"], sum(s["peaks_c"][:2]), s["length_m"]))
        def shortest(target):
            hits = [s for s in scores if np.all(np.asarray(s["peaks_c"][:2]) <= target[:2] + 0.1)]
            return min(hits, key=lambda s: s["length_m"], default=None)
        return dict(count=len(scores), best_joint=best, shortest_old_plus_0p1=shortest(old),
                    shortest_pool_plus_0p1=shortest(oracle))

    groups = {"initial": group(anchors), "all": group(rows)}
    for arm, report in arms.items():
        groups[arm] = group([*anchors, *(t["proposal"] for t in report["trials"])])
    return dict(original_min_c=old.tolist(), pool_min_c=oracle.tolist(), groups=groups,
                returned={arm: point(report["selected"]) for arm, report in arms.items()})


def run(entry, source):
    problem = Problem.from_imported(json.loads(source.read_bytes()))
    sites = sorted(range(problem.count), key=lambda k: (-problem.power_w[k], k))[:4]
    mean = 0.25 * problem.power_w
    mean[sites] = 0.6 * problem.power_w[sites]
    moving = replace(problem, power_w=mean)
    cap = entry["length_cap_m"]
    layouts, names, initial, rejected = {}, {}, {}, []

    def register(layout, label):
        key = layout_key(layout)
        if key not in names:
            names[key] = label
            layouts[label] = layout
        return names[key]

    for r in entry["layouts"]:
        if r["length_m"] > cap:
            continue
        layout = Layout(np.array(r["centre_um"], float), np.array(r["rotation_deg"], int))
        if not is_legal(problem, layout, GAP_UM):
            layout = legalize_relations(problem, layout, GAP_UM)
        length = None if layout is None else geometry(problem, layout)["length_m"]
        if length is None or length > cap:
            rejected.append(dict(source_layout=r["layout"], repaired_m=length))
            continue
        name = register(layout, f"base-{r['layout']}")
        if name not in initial:
            initial[name], _ = measure(problem, entry, source, sites, layout, DWELLS, 32, 4)
    targets = np.min([c.peaks_c for c in initial.values()], axis=0)
    arms = {}
    for arm, visible in (("joint", [0, 1]), ("short", [0]), ("long", [1])):
        started = perf_counter()
        rng = np.random.default_rng(SEED)
        anchors = [replace(c, peaks_c=c.peaks_c[visible], die_peaks_c=c.die_peaks_c[visible])
                   for c in initial.values()]
        durations = [DWELLS[i] for i in visible]

        def propose(parent, temperatures):
            layout = hotspot_move(moving, parent, temperatures, rng, GAP_UM)
            if layout is not None and pin_manhattan_um(problem, layout).sum() / 1e6 <= cap:
                return layout
            return None

        def evaluate(layout):
            return measure(problem, entry, source, sites, layout, durations, 32, 4)[0]

        first, last, trials = search_thermal_targets(anchors, targets[visible], propose, evaluate, budget=24)
        trace = []
        for k, (parent, binding, attempts, candidate, accepted) in enumerate(trials, 1):
            name = register(candidate.layout, f"{arm}-{k:02}")
            trace.append(dict(parent=names[layout_key(parent.layout)], binding_dwell_s=durations[binding],
                              hottest_die=problem.names[int(parent.die_peaks_c[binding].argmax())],
                              attempts=attempts, proposal=name, peaks_c=candidate.peaks_c.tolist(),
                              accepted=accepted))
        arms[arm] = dict(initial=names[layout_key(first.layout)], selected=names[layout_key(last.layout)],
                         visible_dwell_s=durations, queries=len(trials)*len(durations), trials=trace,
                         search_seconds=perf_counter() - started)
        print(entry["case"], arm, arms[arm]["queries"], "queries", flush=True)

    rows = {}
    for name, layout in layouts.items():
        fine, checks = measure(problem, entry, source, sites, layout, (*DWELLS, MIDPOINT), 64, 8, audit=True)
        rows[name] = dict(**geometry(problem, layout), peaks_c=fine.peaks_c.tolist(), replay=checks)
        if len(rows) % 10 == 0:
            print(entry["case"], "audited", len(rows), "/", len(layouts), flush=True)
    return dict(case=entry["case"], source_sha256=digest(source), seed=SEED, gap_um=GAP_UM, length_cap_m=cap,
                chiplet_order=problem.names, alternating_sites=[problem.names[sites[i]] for i in PAIRS[entry["case"]]],
                mean_total_w=float(mean.sum()), amplitude_w=float(0.4 * min(problem.power_w[sites])),
                dwell_s=[*DWELLS, MIDPOINT], search_grid_steps=[32, 4], audit_grid_steps=[64, 8],
                initial_peaks_c={name: c.peaks_c.tolist() for name, c in initial.items()}, rejected=rejected,
                targets_search_c=targets.tolist(), arms=arms, layouts=rows,
                summary=compare_pools(rows, initial, arms))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--case", required=True, choices=PAIRS)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    entries = json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    entry = next(e for e in entries if e["case"] == args.case)
    result = run(entry, args.cases / (args.case + ".json"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
