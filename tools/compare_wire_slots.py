"""Replay the two tight wire caps and verify joint line reassignments on the same 3D package."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement.geometry import is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.slot_margin import choose_hot_slots
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from chiplet_floorplanning.placement.wire_slots import forced_edge_components, line_patterns
from scale_slot_margin import REV, SEED, SlotPackage, problem, score


REFERENCE = Path(__file__).resolve().parents[1] / "docs/evidence/atplace-margin-scale/grid-start.json"


def compare(p, start, reference, checks):
    begin = perf_counter()
    cap = float(pin_manhattan_um(p, start).sum()/1e6)
    np.testing.assert_allclose(cap, reference["cap_m"], rtol=0, atol=1e-12)
    np.testing.assert_array_equal(start.centre_um, reference["start_um"])

    package = SlotPackage(p, start)
    initial = package.temperatures(p.power_w)
    initial_peak = float(initial[package.active].max() + AMBIENT_C)
    np.testing.assert_allclose(initial_peak, reference["peak_start_c"], atol=1e-7, rtol=0)
    for cells in package.slots:
        package.observe(cells[initial[cells].argmax()])
    package.observe(package.active[initial[package.active].argmax()])
    initial_rows = len(package.rows)
    setup_s = perf_counter() - begin

    candidates, counts = line_patterns(p, start, cap)
    rigid = forced_edge_components(p, start, cap)
    options = np.stack([v.power_w for v in candidates])
    # The starting map was already thermally evaluated. Identical maps can have
    # different pin lengths; the representative has the shortest one in this family.
    original = next(i for i, v in enumerate(candidates) if np.array_equal(v.power_w, p.power_w))
    verified = {original: initial_peak}
    trace = []
    def observed_peaks():
        return (np.stack(list(package.rows.values())) @ options.T).max(axis=0) + AMBIENT_C

    for _ in range(checks):
        predicted = observed_peaks()
        unseen = [i for i in range(len(candidates)) if i not in verified]
        if not unseen:
            break
        i = min(unseen, key=lambda j: (predicted[j], candidates[j].wire_m, j))
        v = candidates[i]
        physical = Layout(start.centre_um[v.chip_to_slot], start.rotation_deg)
        wire = float(pin_manhattan_um(p, physical).sum()/1e6)
        assert is_legal(p, physical, 100) and wire <= cap + 1e-9
        np.testing.assert_allclose(wire, v.wire_m, atol=1e-10, rtol=0)
        np.testing.assert_array_equal(v.power_w[v.chip_to_slot], p.power_w)
        field = package.temperatures(v.power_w)
        cell = int(package.active[field[package.active].argmax()])
        peak = float(field[cell] + AMBIENT_C)
        assert predicted[i] <= peak + 1e-7
        verified[i] = peak
        trace.append(dict(chip_to_slot=v.chip_to_slot.tolist(), wire_m=wire,
                          witnessed_peak_c=float(predicted[i]), peak_c=peak,
                          hotspot_cell=cell, new_observer=cell not in package.rows))
        package.observe(cell)

    best = min(verified, key=lambda i: (verified[i], candidates[i].wire_m))
    chosen = candidates[best]
    physical = Layout(start.centre_um[chosen.chip_to_slot], start.rotation_deg)
    assert is_legal(p, physical, 100) and len(np.unique(chosen.chip_to_slot)) == p.count
    exact_wire = float(pin_manhattan_um(p, physical).sum()/1e6)
    assert exact_wire <= cap + 1e-9 and abs(exact_wire - chosen.wire_m) < 1e-10
    np.testing.assert_array_equal(chosen.power_w[chosen.chip_to_slot], p.power_w)
    # The selected power map is independently rebuilt from the actual physical identities.
    report = solve(thermal_case_data(p, physical, 100, 64), node_limit=450000)[0]
    peak = report["peak_power_layer_c"]
    np.testing.assert_allclose(peak, verified[best], atol=1e-6, rtol=0)
    final_witness_peaks = observed_peaks()
    family_floor = float(final_witness_peaks.min() - 1e-7)
    assert family_floor <= peak + 1e-7
    global_floor = reference["peak_selected_c"] - reference["remaining_k"]
    if rigid["all_relative_positions_fixed"]:
        assert len(candidates) == 1 and counts["feasible_identity_assignments"] == 1
        # The reassembled point is the only admissible layout, including outside
        # the restricted search. Different linear solvers can disagree in the last bits.
        global_floor = peak
    assert global_floor <= peak + 1e-7
    reverse = min((i for i in verified if verified[i] <= initial_peak + 1e-8),
                  key=lambda i: (candidates[i].wire_m, verified[i]))
    # Remove an unnecessary axis permutation if its identity mapping gives the
    # same per-slot powers and wire to roundoff. Keep the minimum-wire point above.
    lookup = {tuple(v): i for i, v in enumerate(start.centre_um)}
    examples = []
    start_wires = pin_manhattan_um(p, start) / 1e6
    for axis in (0, 1):
        positions = start.centre_um.copy()
        positions[:, axis] = physical.centre_um[:, axis]
        perm = np.array([lookup[tuple(v)] for v in positions])
        if not np.array_equal(chosen.power_w[perm], p.power_w):
            continue
        distances = pin_manhattan_um(p, Layout(positions, start.rotation_deg)) / 1e6
        difference = distances - start_wires
        if distances.sum() <= cap + 1e-9 and abs(distances.sum() - exact_wire) < 1e-12:
            examples.append(dict(axis=("columns","rows")[axis], chip_to_slot=perm.tolist(),
                moved=int(np.count_nonzero(perm != np.arange(p.count))), wire_m=float(distances.sum()),
                longer_links=int(sum(difference > 1e-12)), shorter_links=int(sum(difference < -1e-12)),
                added_m=float(difference[difference > 1e-12].sum()),
                saved_m=float(-difference[difference < -1e-12].sum())))
    search_elapsed = perf_counter() - begin
    # Price a fresh all-permutation certificate separately. Any subset of
    # observed cells is valid; this uses only rows bought by this search.
    fresh_milp = None
    if rigid["all_relative_positions_fixed"]:
        fresh_floor = peak
    else:
        high = p.power_w.max()
        _, fresh_milp = choose_hot_slots(np.stack(list(package.rows.values())), p.power_w.min(),
                                        high, int(np.sum(p.power_w == high)), time_limit_s=2.)
        fresh_floor = fresh_milp["lower_k"] + AMBIENT_C
    assert fresh_floor <= peak + 1e-7
    return dict(cap_m=cap, initial_peak_c=initial_peak, peak_c=peak, wire_m=exact_wire,
                gain_k=initial_peak-verified[best], chip_to_slot=chosen.chip_to_slot.tolist(),
                same_power_single_axis_examples=examples,
                hot_slots=np.flatnonzero(chosen.power_w == p.power_w.max()).tolist(),
                shortest_at_initial_ceiling=dict(wire_m=candidates[reverse].wire_m,
                    peak_c=verified[reverse], chip_to_slot=candidates[reverse].chip_to_slot.tolist()),
                family_lower_c=family_floor, family_remaining_k=max(0.,peak-family_floor),
                global_lower_c=global_floor, global_remaining_k=max(0.,peak-global_floor),
                fresh_global_lower_c=fresh_floor, fresh_global_remaining_k=max(0.,peak-fresh_floor),
                fresh_milp=fresh_milp, fresh_extra_s=perf_counter()-begin-search_elapsed,
                patterns=[dict(hot_slots=np.flatnonzero(v.power_w == p.power_w.max()).tolist(),
                               min_wire_m=v.wire_m, witnessed_peak_c=float(final_witness_peaks[i]),
                               verified_peak_c=verified.get(i)) for i, v in enumerate(candidates)],
                trace=trace, counts=counts, rigidity=rigid, new_layout_checks=len(trace),
                observer_nodes=list(package.rows),
                initial_adjoint_rows=initial_rows, final_adjoint_rows=len(package.rows),
                setup_s=setup_s, elapsed_including_rebuild_s=search_elapsed,
                balance_error_w=report["energy_balance_error_w"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    actual_rev = subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()
    assert actual_rev == REV
    raw = REFERENCE.read_bytes().replace(b"\r\n", b"\n")
    archive = json.loads(raw)
    assert archive["rapidchiplet"] == REV and archive["seed"] == SEED
    record = dict(seed=SEED, rapidchiplet=REV, reference_sha256=hashlib.sha256(raw).hexdigest(), cases={})
    for rows, cols, topology in [(4, 6, "mesh"), (8, 8, "folded_torus")]:
        start_input = perf_counter()
        p, start = problem(rows, cols, topology, upstream, False, True)
        input_s = perf_counter() - start_input
        name = p.name + "_grid_start"
        reference = archive["cases"][name]
        baseline = score(p, start, False)
        np.testing.assert_allclose(baseline["peak_selected_c"], reference["peak_selected_c"], atol=1e-6, rtol=0)
        np.testing.assert_allclose(baseline["remaining_k"], reference["remaining_k"], atol=1e-5, rtol=0)
        limit = len(reference["trace"])
        assert limit == 2 and len(baseline["trace"]) == limit
        joint = compare(p, start, reference, limit)
        joint["total_s"] = joint["elapsed_including_rebuild_s"] + input_s
        record["cases"][name] = dict(baseline=dict(peak_c=baseline["peak_selected_c"],
            wire_m=baseline["wire_m"], thermal_relaxation_remaining_k=baseline["remaining_k"],
            total_s=baseline["with_independent_audit_s"]+input_s, trace=baseline["trace"],
            adjoints=baseline["adjoints"]), joint=joint, shared_input_s=input_s)
        print(name, "gain / remaining (K)", joint["gain_k"], joint["global_remaining_k"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, allow_nan=False)+"\n", encoding="utf8",newline="\n")


if __name__ == "__main__":
    main()
