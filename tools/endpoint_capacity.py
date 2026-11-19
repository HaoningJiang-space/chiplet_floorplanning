"""Certify all steady directed traffic with equal per-CPU send and receive limits."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import permutations
import json
from pathlib import Path

import numpy as np

from case3_phy_geometry import CAP_M, LIMIT_C, PAYLOAD_FRACTION, REACH_MM
from chiplet_floorplanning.placement import Problem
from cut_traffic import EVIDENCE, digest
from module_capacity import CAPACITY, GRIDS, MODULES, bank_table
from shared_capacity import TARGET, physical_capacity, routed_load, thermal_job


def matchings():
    full = []
    partial = {}
    for perm in permutations(range(4)):
        D = np.zeros((4, 4))
        for i, j in enumerate(perm):
            if i != j:
                D[i, j] = TARGET * 8000 / (4 * PAYLOAD_FRACTION)
        full.append((perm, D))
        for mask in range(16):
            subset = D.copy()
            subset[[(mask & (1 << i)) == 0 for i in range(4)], :] = 0
            partial[tuple(subset.ravel())] = subset
    return full, list(partial.values())


def partial_check(job):
    mods, target, partial = job
    worst = 0.0
    cap = 256 * np.array(mods)
    for d in partial:
        flow = routed_load(d * (target / TARGET), cap)
        worst = max(worst, float((flow - cap[:, None]).max()))
    return dict(
        modules=mods,
        target_TB_s=target,
        partial_matchings=len(partial),
        max_overload_gbps=worst,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "output"):
        ap.add_argument("--" + k, type=Path, required=True)
    args = ap.parse_args()
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    assert (
        digest(src)
        == json.loads((EVIDENCE / "capacity-cost-v1.json").read_text())[
            "physical_model"
        ]["raw_source_sha256"]
    )
    p = Problem.from_imported(json.loads(src.read_text()))
    rows = json.loads((EVIDENCE / "case3-selective-rate-v1.json").read_text())[
        "threshold_witnesses"
    ]
    full, partial = matchings()
    active = np.array([d for _, d in full if d.any()])
    results = []
    jobs = {}
    selected = set()
    with ProcessPoolExecutor(7) as pool:
        rates = np.array(
            list(
                pool.map(
                    physical_capacity,
                    [(i, active) for i in range(len(MODULES))],
                    chunksize=4,
                )
            )
        )
        for row in rows:
            mem, cost, reach = bank_table(p, row)
            wire = mem + cost[np.arange(4), MODULES].sum(axis=1)
            longest = reach[np.arange(4), MODULES].max(axis=1)
            for target in (TARGET, 0.24):
                allowed = (rates.min(axis=1) >= target - 1e-9) & (
                    longest <= REACH_MM + 1e-9
                )
                assert allowed.any()
                i = int(np.argmin(np.where(allowed, wire, np.inf)))
                mods = tuple(MODULES[i].tolist())
                selected.add((mods, target))
                modes = []
                for perm, d in full:
                    load = routed_load(d * (target / TARGET), CAPACITY[i])
                    watts = tuple(
                        (
                            (0.25 * CAPACITY[i] + 0.75 * load.mean(axis=1)) / 1000
                        ).tolist()
                    )
                    m = dict(destinations=list(perm), endpoint_w=watts)
                    modes.append(m)
                    jobs.setdefault((row["id"], mods, watts), []).append(m)
                results.append(
                    dict(
                        layout=row["id"],
                        target_TB_s=target,
                        per_cpu_payload_TB_s=target / 4,
                        feasible_portfolios=int(allowed.sum()),
                        modules=mods,
                        wire_m=float(wire[i]),
                        max_cpu_signal_mm=float(longest[i]),
                        min_service_nominal_TB_s=float(rates[i].min()),
                        terminal_modes=modes,
                    )
                )
        checked = list(
            pool.map(partial_check, [(m, t, partial) for m, t in sorted(selected)])
        )
        todo = [
            (p, r, m, w, g)
            for r in rows
            for rid, m, w in jobs
            if rid == r["id"]
            for g in GRIDS
        ]
        for key, g, t in pool.map(thermal_job, todo):
            for z in jobs[key]:
                z.setdefault("grids", {})[g] = t
    for r in results:
        r["worst_peak_c"] = max(
            z["peak_c"] for m in r["terminal_modes"] for z in m["grids"].values()
        )
        r["joint_target_met"] = bool(
            r["wire_m"] <= CAP_M + 1e-10 and r["worst_peak_c"] <= LIMIT_C
        )
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                source_sha256=digest(src),
                targets=results,
                full_permutations=len(full),
                partial_matchings=len(partial),
                partial_checks=checked,
                portfolio_directed_lp_count=rates.size,
                unique_thermal_solves=len(todo),
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
