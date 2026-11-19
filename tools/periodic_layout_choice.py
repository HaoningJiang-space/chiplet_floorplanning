"""Local paired comparison of floorplan and task order under a fixed work quota."""
import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package, require_heat_path
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.periodic import balanced_orders, cycle_trace, periodic_pulse, quota_peak
from chiplet_floorplanning.placement.thermal import thermal_case_data
from chiplet_floorplanning.power import rasterize
from cut_traffic import EVIDENCE, digest
from layout_dominance import workload
from thermal_history import capacities


SLOTS = 8
ORDERS = balanced_orders(SLOTS)
ALTERNATE = "01" * 4
BLOCK = "00001111"
DURATIONS = [.005, .05, .5]


def package_model(data):
    powers = []
    for item in data:
        case = parse_case(item, node_limit=450000)
        power, _ = rasterize(case)
        g, rhs, sink, _, ids, layer = assemble_package(case, power)
        if not powers:
            reference = g
            mesh = case.mesh
            require_heat_path(g, sink)
        else:
            assert mesh == case.mesh and (reference != g).nnz == 0
        powers.append(rhs)
    observed = ids[layer][ids[layer] >= 0]
    return g, capacities(case, ids), np.column_stack(powers), sink, observed, case.thermal["ambient_c"]


def replay(g, capacity, powers, sink, initial, order, slot, substeps, observed, ambient):
    cd = capacity * substeps / slot
    factor = splu((g + diags(cd)).tocsc(), permc_spec="MMD_AT_PLUS_A")
    state = initial
    peak, balance = -np.inf, 0.
    for bit in order:
        source = powers[:, int(bit)]
        for _ in range(substeps):
            updated = factor.solve(cd * state + source)
            imbalance = cd @ (updated-state) + sink @ updated - source.sum()
            balance = max(balance, abs(float(imbalance)))
            peak = max(peak, float(updated[observed].max()) + ambient)
            state = updated
    closure = float(abs(state - initial).max())
    assert closure < 1e-6 and balance < 1e-6
    return dict(direct_peak_c=peak, closure_k=closure, max_energy_error_w=balance)


def trial(model, slot, substeps, audit):
    g, cap, powers, sink, nodes, ambient = model
    steady, full = periodic_pulse(g, cap, powers, slot, substeps, SLOTS)
    period_average = steady[nodes].mean(axis=1) + ambient
    base, pulse = steady[nodes, 0] + ambient, full[:, nodes]
    peaks = {}
    for order in ORDERS:
        trace = cycle_trace(base, pulse, order)
        np.testing.assert_allclose(trace.mean(axis=0), period_average, atol=1e-8, rtol=0)
        peaks[order] = float(trace.max())
    worst = max(peaks.values())
    bound = quota_peak(base, pulse, SLOTS, SLOTS//2)
    assert abs(worst - bound) < 1e-8
    row = dict(slot_s=slot, mean_peak_c=float(period_average.max()), peaks_c=peaks,
               task_powers_w=powers.sum(axis=0).tolist(), best_peak_c=min(peaks.values()),
               worst_peak_c=worst, sorted_quota_peak_c=bound)
    if audit:
        # Rebuild a single initial state and march chronologically with imposed power.
        order = "00110101"
        state = steady[:, 0] + sum(full[(-1 - i*substeps) % len(full)]
                                   for i, bit in enumerate(order) if bit == "1")
        row["replay"] = replay(g, cap, powers, sink, state, order, slot, substeps, nodes, ambient)
        canonical = min(order[i:] + order[:i] for i in range(SLOTS))
        assert abs(row["replay"]["direct_peak_c"] - peaks[canonical]) < 1e-6
    return row


def decisions(rows):
    def pick(metric):
        return min(rows, key=lambda r: (r[metric], r["length_m"], r["layout"]))
    mean, robust, joint = (pick(k) for k in ["mean_peak_c", "worst_peak_c", "best_peak_c"])
    reverse = []
    for a, b in combinations(rows, 2):
        differences = {o: a["peaks_c"][o] - b["peaks_c"][o] for o in ORDERS}
        low, high = min(differences, key=differences.get), max(differences, key=differences.get)
        if differences[low] < -1e-6 and differences[high] > 1e-6:
            reverse.append(dict(a=a["layout"], b=b["layout"], low_order=low, high_order=high,
                                low_k=differences[low], high_k=differences[high]))
    return dict(mean_layout=mean["layout"], robust_layout=robust["layout"], joint_layout=joint["layout"],
                start_worst_c=mean["worst_peak_c"], robust_c=robust["worst_peak_c"], joint_c=joint["best_peak_c"],
                reschedule_only_gain_k=mean["worst_peak_c"]-mean["best_peak_c"],
                replan_only_gain_k=mean["worst_peak_c"]-robust["worst_peak_c"],
                joint_gain_k=mean["worst_peak_c"]-joint["best_peak_c"], reversals=reverse)


def study(name, cap, inputs, slots, grid, substeps):
    per_slot = {slot: [] for slot in slots}
    for idx, (layout, length, data) in enumerate(inputs):
        model = package_model(data)
        for slot in slots:
            r = trial(model, slot, substeps, audit=idx == 0 and (slot == .05 or len(slots) == 1))
            per_slot[slot].append(dict(layout=layout, length_m=length, **r))
    return dict(name=name, grid=grid, substeps=substeps, length_cap_m=cap,
                times=[dict(slot_s=s, layouts=v, decision=decisions(v)) for s, v in per_slot.items()])


def atplace_inputs(path, row, grid):
    assert digest(path) == row["input_sha256"]
    p = Problem.from_imported(json.loads(path.read_bytes()))
    powers, _ = workload(p)
    inputs = []
    for r in row["layouts"]:
        layout = Layout(np.array(r["centre_um"]), np.array(r["rotation_deg"]))
        assert is_legal(p, layout, 0)
        length = float(pin_manhattan_um(p, layout).sum()/1e6)
        if length <= row["length_cap_m"]:
            data = [thermal_case_data(replace(p, power_w=w), layout, 0, grid) for w in powers]
            inputs.append((r["layout"], length, data))
    assert {i for i, _, _ in inputs} == {r["layout"] for r in row["candidates"]}
    return inputs


def atplace(path, row, slots, grid, substeps):
    return study(row["case"], row["length_cap_m"], atplace_inputs(path, row, grid), slots, grid, substeps)


def nas_inputs(source, grid, modes):
    from mixed_phy import bank_thermal_data
    from module_capacity import bank_table, profile

    archive = json.loads((EVIDENCE / "shared-capacity-v1.json").read_bytes())
    previous = json.loads((EVIDENCE / "case3-nas-dominance-v1.json").read_bytes())
    geom = json.loads((EVIDENCE / "case3-selective-rate-v1.json").read_bytes())["threshold_witnesses"]
    assert digest(source) == previous["case_sha256"]
    problem = Problem.from_imported(json.loads(source.read_bytes()))
    rows = {r["id"]: r for r in geom}
    inputs = []
    for r in archive["physical"]["layout_trials"]:
        name = r["layout"]
        solution = next(t["sized"] for t in r["cases"] if t["target_TB_s"] == previous["target_TB_s"])
        modules = np.array(solution["modules"])
        row = rows[name]
        memory, length, reach = bank_table(problem, row)
        key = np.arange(len(modules)), modules
        wire = float(memory + length[key].sum())
        if wire > previous["length_cap_m"] or reach[key].max() > previous["reach_mm"] + 1e-9:
            continue
        profiles = [profile(m) for m in modules]
        data = [bank_thermal_data(problem, row, row["actual_config"], grid, profiles, solution["modes"][k]["endpoint_w"])
                for k in modes]
        inputs.append((name, wire, data))
    assert len(inputs) == 2
    return previous["length_cap_m"], inputs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True, help="directory with imported Case1.json through Case10.json")
    ap.add_argument("--phase", choices=["discovery", "confirmation", "fine", "nas"], required=True)
    ap.add_argument("--screen", type=Path, nargs=2, help="discovery and confirmation records for selecting the fine replay")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    cases = json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    if args.phase == "nas":
        cap, inputs = nas_inputs(args.cases/"Case3.json", 64, ["IS", "WH"])
        results = [study("Case3 NAS IS/WH", cap, inputs, DURATIONS, 64, 4)]
    elif args.phase == "fine":
        if not args.screen:
            ap.error("--phase fine requires --screen discovery.json confirmation.json")
        screens = [r for p in args.screen for r in json.loads(p.read_bytes())["cases"]]
        name, slot, _ = max(((r["name"], s["slot_s"], s["decision"]["replan_only_gain_k"])
                             for r in screens for s in r["times"]), key=lambda t: t[2])
        row = next(c for c in cases if c["case"] == name)
        results = [atplace(args.cases/f"{name}.json", row, [slot], grid, 8) for grid in (32, 64)]
    else:
        chosen = cases[:5] if args.phase == "discovery" else cases[5:]
        results = []
        for row in chosen:
            results.append(atplace(args.cases/(row["case"]+".json"), row, DURATIONS, 32, 2))
            print(row["case"], [round(s["decision"]["replan_only_gain_k"], 3) for s in results[-1]["times"]], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(phase=args.phase, cases=results), indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
