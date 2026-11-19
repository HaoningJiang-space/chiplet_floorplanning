"""Thermal bounds for switched power maps on a fixed, passive package."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path
import socket

import numpy as np
from scipy.linalg import expm
from scipy.sparse import diags
from scipy.sparse.linalg import splu

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import (
    assemble_package,
    checked_solution,
    rectangle_slice,
    require_heat_path,
    solve_spd,
)
from chiplet_floorplanning.placement import Problem
from chiplet_floorplanning.power import rasterize
from cut_traffic import EVIDENCE, digest
from mixed_phy import bank_thermal_data
from module_capacity import GRIDS, profile


# Nominal volumetric heat capacities, J/(m³ K). Effective composite layers
# use the same nominal footprint fractions as the fixed conductance model.
MATERIAL = dict(
    silicon=1.75e6, copper=3.55e6, tim=4e6, underfill=2.65e6, substrate=1.60e6
)
SLOTS = 10
SLOT_S = 0.05
TEMPERATURE_LIMIT_C = 109.0
EVIDENCE_NAMES = (
    "case3-selective-rate",
    "any-traffic",
    "shared-capacity",
    "capacity-cost",
)


def capacities(case, ids):
    def mixture(background, fraction):
        return (1 - fraction) * MATERIAL[background] + fraction * MATERIAL["copper"]

    bulk = dict(
        substrate=MATERIAL["substrate"],
        c4=mixture("underfill", (250 / 600) ** 2),
        interposer=mixture("silicon", (10 / 50) ** 2),
        microbumps=MATERIAL["underfill"],
        dies=MATERIAL["underfill"],
        tim=MATERIAL["tim"],
        spreader=MATERIAL["copper"],
        sink=MATERIAL["copper"],
    )
    die_values = dict(
        dies=MATERIAL["silicon"], microbumps=mixture("underfill", (25 / 45) ** 2)
    )
    result = np.empty(int(ids.max()) + 1)
    for layer, index in zip(case.thermal["layers"], ids):
        name = layer["id"]
        density = np.full(index.shape, bulk[name])
        if name in die_values:
            for die in case.dies:
                density[rectangle_slice(case, die.bounds)] = die_values[name]
        active = index >= 0
        volume_m3 = case.mesh.areas_mm2[active] * layer["thickness_mm"] * 1e-9
        result[index[active]] = density[active] * volume_m3
    assert np.all(result > 0)
    return result


def past_envelope(steady_fields, observation_ids, evolve_free, slots):
    """Temperature-rise contributions for independent slots and one steady prehistory.

    evolve_free advances all mode columns by one unforced slot. For mode m,
    (I-M)G^-1 P_m is its response to one powered slot, and M^k translates
    that response k slots into the past. Differences from a common steady
    reference leave each slot's maximizing choice unchanged.
    """
    ref = steady_fields[:, :1]
    remaining = steady_fields - ref
    envelope = ref[observation_ids, 0].copy()
    recent_first = []
    for _ in range(slots):
        older = evolve_free(remaining)
        weight = remaining[observation_ids] - older[observation_ids]
        recent_first.append(weight.argmax(axis=1))
        envelope += weight.max(axis=1)
        remaining = older
    tail = remaining[observation_ids]
    return envelope + tail.max(axis=1), tail.argmax(axis=1), recent_first[::-1]


def exact_controls():
    # Equal 1 J/K capacitors, 1 W/K between nodes and from each node to air.
    g = np.array([[2.0, -1.0], [-1.0, 2.0]])
    powers = np.array([[3.0, 2.0], [0.0, 2.0]])
    ss = np.linalg.solve(g, powers)
    time_s = np.log(3) / 2
    witness = ss[:, 0] + expm(-g * time_s) @ (ss[:, 1] - ss[:, 0])
    peak = 2 + 1 / (3 * np.sqrt(3))
    assert abs(witness.max() - peak) < 1e-12
    controls = []
    for topology, edges in dict(
        chain=[(0, 1), (1, 2), (2, 3), (3, 4)],
        ring=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)],
        star=[(0, 1), (0, 2), (0, 3), (0, 4)],
        grid=[(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)],
    ).items():
        n = max(max(e) for e in edges) + 1
        net = np.diag(np.linspace(0.0, 1.0, n))
        for i, (a, b) in enumerate(edges):
            link = np.eye(n)[a] - np.eye(n)[b]
            net += (1 + i / 7) * np.outer(link, link)
        capacity = np.linspace(0.7, 2.0, n)
        power = np.eye(n)[:, [0, n // 2, n - 1]] * np.array([1.0, 2.0, 3.0])
        steady = np.linalg.solve(net, power)
        step = expm(-0.17 * net / capacity[:, None])
        envelope, _, _ = past_envelope(steady, np.arange(n), lambda x: step @ x, 6)
        # Direct chronological forward integration enumerates 3^7 histories.
        driven = (np.eye(n) - step) @ steady
        exhaustive = np.full(n, -np.inf)
        for history in product(range(3), repeat=7):
            state = steady[:, history[0]]
            for mode in history[1:]:
                state = step @ state + driven[:, mode]
            exhaustive = np.maximum(exhaustive, state)
        error = float(np.max(abs(exhaustive - envelope)))
        assert error < 1e-11
        controls.append(dict(topology=topology, histories=3**7, error_inf_k=error))
    return dict(
        steady_max_rise_k=float(ss.max()),
        switch_before_peak_s=float(time_s),
        analytic_peak_rise_k=float(peak),
        direct_peak_rise_k=float(witness.max()),
        exhaustive_controls=controls,
    )


def time_trial(g, sink, capacity, power, steady, observed, ambient, names, substeps):
    dt = SLOT_S / substeps
    cd = capacity / dt
    lu = splu((g + diags(cd)).tocsc(), permc_spec="MMD_AT_PLUS_A")

    def free_slot(x):
        for _ in range(substeps):
            x = lu.solve(cd[:, None] * x)
        return x

    envelope, initial, order = past_envelope(steady, observed, free_slot, SLOTS)
    winner = int(envelope.argmax())
    initial_mode = initial[winner]
    chronological = [slot[winner] for slot in order]
    # Independent driven forward replay, in absolute rise from ambient. Also
    # checks power at every step against stored heat and convective removal.
    state = steady[:, initial_mode]
    max_ledger = 0.0
    for mode in chronological:
        for _ in range(substeps):
            updated = lu.solve(power[:, mode] + cd * state)
            imbalance = (
                capacity @ (updated - state) / dt
                + sink @ updated
                - power[:, mode].sum()
            )
            max_ledger = max(max_ledger, abs(float(imbalance)))
            state = updated
    error = float(abs(state[observed[winner]] - envelope[winner]))
    assert error < 1e-7 and max_ledger < 1e-6
    return dict(
        dt_s=dt,
        slots=SLOTS,
        slot_s=SLOT_S,
        peak_c=float(ambient + envelope[winner]),
        max_above_local_steady_k=float(np.max(envelope - steady[observed].max(axis=1))),
        peak_node=int(observed[winner]),
        steady_prehistory=names[initial_mode],
        oldest_to_newest=[names[k] for k in chronological],
        target_replay_error_k=error,
        max_step_energy_balance_w=max_ledger,
    )


def evaluate(job):
    source, design_name, row, modules, modes, grid = job
    p = Problem.from_imported(json.loads(source.read_text()))
    profiles = [profile(m) for m in modules]
    names = sorted(modes)
    columns = []
    for name in names:
        watts = modes[name]["endpoint_w"]
        data = bank_thermal_data(p, row, row["actual_config"], grid, profiles, watts)
        case = parse_case(data, node_limit=450000)
        field, _ = rasterize(case)
        if not columns:
            g, _, sink, _, ids, z = assemble_package(case, field)
            require_heat_path(g, sink)
            capacity = capacities(case, ids)
            ambient = case.thermal["ambient_c"]
            active = ids[z] >= 0
            observed = ids[z][active]
            mesh = case.mesh
        assert mesh == case.mesh
        rhs = np.zeros(g.shape[0])
        rhs[observed] = field[active]
        assert abs(rhs.sum() - p.power_w.sum() - 2 * sum(watts)) < 1e-7
        columns.append(rhs)
    power = np.column_stack(columns)
    steady = []
    for rhs in [*columns, power.max(axis=1)]:
        theta = solve_spd(g, rhs)
        checked_solution(g, rhs, sink, theta)
        steady.append(theta)
    upper = steady.pop()
    steady = np.column_stack(steady)
    peaks = steady[observed].max(axis=0) + ambient
    for i, name in enumerate(names):
        assert abs(peaks[i] - modes[name]["peak_c_by_grid"][str(grid)]) < 1e-7
    bound = float(upper[observed].max() + ambient)
    trials = []
    if grid in (64, 96):
        for substeps in (1, 2, 4):
            trial = time_trial(
                g, sink, capacity, power, steady, observed, ambient, names, substeps
            )
            assert peaks.max() - 1e-7 <= trial["peak_c"] <= bound + 1e-7
            trials.append(trial)
    return dict(
        design=design_name,
        layout=row["id"],
        modules=modules,
        grid=grid,
        nodes=g.shape[0],
        total_capacity_j_per_k=float(capacity.sum()),
        steady_mode_peak_c=dict(zip(names, peaks.tolist())),
        arbitrary_switch_upper_c=bound,
        guaranteed_margin_k=TEMPERATURE_LIMIT_C - bound,
        steady_lower_c=float(peaks.max()),
        timed_trials=trials,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="results root containing imported Case3",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    inputs = {k: EVIDENCE / (k + "-v1.json") for k in EVIDENCE_NAMES}
    records = {k: json.loads(path.read_text()) for k, path in inputs.items()}
    source = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    assert (
        digest(source)
        == records["capacity-cost"]["physical_model"]["raw_source_sha256"]
    )
    row = records["case3-selective-rate"]["threshold_witnesses"][0]
    pairs = records["any-traffic"]["targets"][0]
    nas = records["shared-capacity"]["physical"]["layout_trials"][0]
    assert row["id"] == pairs["layout"] == nas["layout"]
    case = nas["cases"][0]
    assert pairs["target_payload_TB_s"] == case["target_TB_s"] == 0.2
    nas_sized = case["sized"]
    designs = [
        ("any-pair", pairs["modules"], pairs["terminal_modes"]),
        ("nas", nas_sized["modules"], nas_sized["modes"]),
    ]
    controls = exact_controls()
    jobs = [
        (source, design, row, modules, modes, grid)
        for grid in GRIDS
        for design, modules, modes in designs
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        cases = list(pool.map(evaluate, jobs))
    out = dict(
        protocol_commit="52ed7471ec8ba2ce1557ada1787f2933d4b62db9",
        analysed_commit="8c81a562fe5cdb7fc5722f7a1ad8320f249ec07e",
        fetch_succeeded=True,
        host=socket.gethostname(),
        source_sha256=digest(source),
        input_sha256={k: digest(v) for k, v in inputs.items()},
        driver_sha256=digest(Path(__file__)),
        material_j_per_m3_k=MATERIAL,
        limit_c=TEMPERATURE_LIMIT_C,
        controls=controls,
        cases=cases,
    )
    with args.output.open("x") as f:
        json.dump(out, f, indent=2, allow_nan=False)
        f.write("\n")


if __name__ == "__main__":
    main()
