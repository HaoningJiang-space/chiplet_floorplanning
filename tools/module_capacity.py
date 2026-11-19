"""Exhaustively size four centered x16 banks at three frozen Case3 layouts."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import product
import json
from pathlib import Path

import numpy as np

from capacity_cost import MODULE_GBPS, SIGNALS, flow_design, shortest_design
from case3_phy_geometry import (
    CAP_M,
    LIMIT_C,
    NEIGHBOURS,
    PAYLOAD_FRACTION,
    REACH_MM,
    RING,
    bank,
    sizes_mm,
)
from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um
from cut_traffic import EVIDENCE, MATCHINGS, digest
from mixed_phy import MID, bank_temperature, temperature

EDGES = np.array(RING)
MODULES = np.array(list(product(range(5), repeat=4)))
CAPACITY = MODULES * MODULE_GBPS
UNIFORM = np.ptp(MODULES, axis=1) == 0
CUTS = np.array([[bool(mask & (1 << i)) for i in range(4)] for mask in range(1, 15, 2)])
CROSSES = CUTS[:, EDGES[:, 0]] != CUTS[:, EDGES[:, 1]]
SUPPLY = CAPACITY @ CROSSES.T
REFERENCE = {(18, 18, 4), (24, 12, 4)}
GRIDS = (64, 96, 128, 160, 192)


def profile(modules):
    return replace(MID, modules=int(modules))


def bank_table(p, row):
    xy = np.array(row["centres_um"]) / 1000
    cfg = row["actual_config"]
    layout = Layout(np.array(row["centres_um"]), np.array(cfg["rotation_deg"]))
    assert is_legal(p, layout, 0)
    size = sizes_mm(p, row["parity"])
    memory = pin_manhattan_um(p, layout)[(p.pin_chip >= 4).any(axis=1)].sum() / 1e6
    assert abs(memory - cfg["memory_m"]) < 1e-8
    cost = np.zeros((4, 5))
    reach = np.zeros_like(cost)
    for e, (a, b) in enumerate(RING):
        for m in range(1, 5):
            pads = []
            for i, j in ((a, b), (b, a)):
                side = cfg["sides"][i][NEIGHBOURS[i].index(j)]
                offsets, _ = bank(tuple(size[i]), side, profile(m))
                assert np.all(abs(offsets) <= size[i] / 2 + 1e-9)
                pads.append(xy[i] + offsets)
            d = abs(pads[0] - pads[1]).sum(axis=1)
            assert len(d) == m * SIGNALS
            cost[e, m] = d.sum() / 1000
            reach[e, m] = d.max()
            assert cost[e, m] >= m * cost[e, 1] - 1e-10
    assert (np.diff(reach) >= -1e-9).all()
    return float(memory), cost, reach


def workload(shares, target):
    raw_per_cpu = target * 8000 / (4 * PAYLOAD_FRACTION)
    demand = np.zeros((4, 4))
    for count, matching in zip(shares, MATCHINGS):
        for a, b in matching:
            demand[a, b] = demand[b, a] = raw_per_cpu * count / 40
    assert abs(demand.sum() * PAYLOAD_FRACTION / 8000 - target) < 1e-12
    crossing = np.array([demand[np.ix_(s, ~s)].sum() for s in CUTS])
    return demand, crossing


def routing(index, demand, memory, wire, reach):
    cap = CAPACITY[index]
    _, load, err = flow_design(EDGES, np.zeros(4), demand, cap, min_hops=True)
    assert np.all(load <= cap + 1e-7)
    # At 1 pJ/bit the bidirectional link draws 2*raw_gbps/1000 W at full service.
    # Each endpoint accounts for half of that aggregate power.
    endpoint = (0.25 * cap + 0.75 * load) / 1000
    return dict(
        modules=MODULES[index].tolist(),
        capacity_each_direction_gbps=cap.tolist(),
        routed_each_direction_gbps=load.tolist(),
        max_cpu_signal_mm=float(reach[index]),
        endpoint_w=endpoint.tolist(),
        phy_w=float(2 * endpoint.sum()),
        total_wire_m=float(wire[index]),
        cpu_wire_m=float(wire[index] - memory),
        flow_residual_gbps=err,
    )


def compare_layout(p, row):
    memory, cost, reach = bank_table(p, row)
    indices = np.arange(4)
    wire = memory + cost[indices, MODULES].sum(axis=1)
    longest = reach[indices, MODULES].max(axis=1)
    legal = longest <= REACH_MM + 1e-9
    limit = np.sum(reach[:, 1:] <= REACH_MM + 1e-9, axis=1) * MODULE_GBPS
    price = cost[:, 1] / MODULE_GBPS
    match_prices = []
    for k in range(3):
        shares = tuple(40 * int(i == k) for i in range(3))
        d, _ = workload(shares, 1.0)
        match_prices.append(shortest_design(EDGES, price, d)[0])
    reports = []
    refs = []
    for target in (0.65, 0.80):
        gaps = []
        savings = []
        totals = within_cap = uniform_within_cap = 0
        for i in range(41):
            for j in range(41 - i):
                shares = (i, j, 40 - i - j)
                d, cross = workload(shares, target)
                attainable = legal & (SUPPLY + 1e-8 >= cross).all(axis=1)
                totals += 1
                ref = dict(
                    shares=list(shares),
                    target_TB_s=target,
                    reachable=bool(attainable.any()),
                )
                if not attainable.any():
                    if shares in REFERENCE:
                        refs.append(ref)
                    continue
                best = int(np.argmin(np.where(attainable, wire, np.inf)))
                same = attainable & UNIFORM
                best_same = (
                    int(np.argmin(np.where(same, wire, np.inf))) if same.any() else None
                )
                predicted = target * np.dot(shares, match_prices) / 40
                gap = float(wire[best] - memory - predicted)
                assert gap >= -1e-7
                gaps.append(gap)
                within_cap += int(wire[best] <= CAP_M + 1e-10)
                if best_same is not None:
                    savings.append(float(wire[best_same] - wire[best]))
                    uniform_within_cap += int(wire[best_same] <= CAP_M + 1e-10)
                if shares not in REFERENCE:
                    continue
                closed, load = shortest_design(EDGES, price, d)
                capped, capped_load, _ = flow_design(EDGES, price, d, limit)
                assert (
                    abs(closed - predicted) < 1e-8
                    and abs(price @ capped_load - capped) < 1e-8
                )
                rounded = np.ceil(capped_load / MODULE_GBPS - 1e-10).astype(int)
                rounded_index = int(np.ravel_multi_index(tuple(rounded), (5,) * 4))
                assert (
                    attainable[rounded_index]
                    and wire[best] <= wire[rounded_index] + 1e-8
                )
                assert closed <= capped + 1e-8 and capped <= wire[best] - memory + 1e-8
                ref.update(
                    uncapped_cpu_floor_m=closed,
                    uncapped_shortest_load_gbps=load.tolist(),
                    capped_linear_cpu_floor_m=capped,
                    capped_rounded_modules=rounded.tolist(),
                    capped_rounded_wire_m=float(wire[rounded_index]),
                    sized=routing(best, d, memory, wire, longest),
                    uniform=(
                        routing(best_same, d, memory, wire, longest)
                        if best_same is not None
                        else None
                    ),
                )
                refs.append(ref)
        reports.append(
            dict(
                target_TB_s=target,
                matrices=totals,
                reachable=len(gaps),
                uniform_reachable=len(savings),
                within_wire_cap=within_cap,
                uniform_within_wire_cap=uniform_within_cap,
                median_excess_over_continuous_m=(
                    float(np.median(gaps)) if gaps else None
                ),
                common_matrices_with_wire_savings=sum(s > 1e-8 for s in savings),
                median_wire_saving_m=float(np.median(savings)) if savings else None,
            )
        )
    return dict(
        layout=row["id"],
        memory_m=memory,
        cpu_bank_wire_m=cost.tolist(),
        cpu_bank_reach_mm=reach.tolist(),
        reports=reports,
        reference=refs,
    )


def thermal_job(job):
    p, row, modules, endpoint, grid = job
    check = bank_temperature(
        p,
        row,
        row["actual_config"],
        grid,
        [profile(m) for m in modules],
        endpoint,
        node_limit=450000,
    )
    return (row["id"], modules, endpoint), grid, check


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    prior = EVIDENCE / "case3-selective-rate-v1.json"
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    authority = json.loads((EVIDENCE / "case3-joint-clearance-v1.json").read_text())
    expected = next(
        c["case_sha256"]
        for c in authority["source_case_checks"]["cases"]
        if c["case"] == "Case3"
    )
    assert digest(src) == expected
    p = Problem.from_imported(json.loads(src.read_text()))
    rows = json.loads(prior.read_text())["threshold_witnesses"]
    trials = [compare_layout(p, r) for r in rows]
    # Replay one archived full-power result for each geometry through the shared thermal entry point.
    control = []
    for row in rows:
        obs = temperature(p, row, row["mask"], row["actual_config"], 64)
        error = abs(obs["peak_c"] - row["checks"]["64"]["peak_c"])
        assert error < 1e-6
        control.append(error)
    jobs = {}
    for row, trial in zip(rows, trials):
        for ref in trial["reference"]:
            if ref["reachable"]:
                for method in ("sized", "uniform"):
                    config = ref[method]
                    if config is not None:
                        key = (
                            row["id"],
                            tuple(config["modules"]),
                            tuple(config["endpoint_w"]),
                        )
                        jobs.setdefault(key, []).append(config)
    todo = [
        (p, row, mods, watts, g)
        for row in rows
        for rid, mods, watts in jobs
        if rid == row["id"]
        for g in GRIDS
    ]
    with ProcessPoolExecutor(args.workers) as pool:
        for key, grid, obs in pool.map(thermal_job, todo, chunksize=1):
            for cfg in jobs[key]:
                cfg.setdefault("thermal", {})[grid] = obs
    for configs in jobs.values():
        for cfg in configs:
            cfg["max_peak_c"] = max(c["peak_c"] for c in cfg["thermal"].values())
            cfg["joint_target_met"] = bool(
                cfg["total_wire_m"] <= CAP_M + 1e-10 and cfg["max_peak_c"] <= LIMIT_C
            )
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                prior_sha256=digest(prior),
                case_sha256=digest(src),
                thermal_replay_error_c=control,
                fresh_thermal_solves=len(todo),
                layouts=trials,
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
