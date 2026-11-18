"""Search Case3 wide-PHY floorplans at matched throughput over a fixed wire-budget ladder."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path
import numpy as np

from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import (
    CAP_M,
    PROFILES,
    RING,
    NEIGHBOURS,
    direct_check,
    edge_matrices,
    heat_score,
    memory_states,
    sizes_mm,
    select_ports,
)
from case3_phy_thermal import solve_field
from chiplet_floorplanning.placement import Layout, is_legal
from case3_wire_witness import thermal_key
from compare_wire_heat import digest
from wide_floorplan_moves import move

FACTORS = (1.0, 1.125, 1.25, 1.5, 2.0)
NAME = "wide"


def screen(row):
    p = STATE["p"]
    xy = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    mem, turns = memory_states(xy, row["parity"], STATE["costs"])
    c = select_ports(xy, size, mem, turns, PROFILES[NAME])
    return dict(
        row,
        profiles={NAME: c},
        score=heat_score(
            xy, size, p.power_w, STATE["radii"], STATE["weights"], STATE["self_k"]
        ),
    )


def families(p):
    rows = []
    seen = set()
    proposals = 0
    for axis, sign, g, t, x, y in product(
        range(2),
        (-1, 1),
        (0.0, 1.5),
        (-2.0, -0.334, 0.0, 0.334, 2.0),
        np.arange(4.5, 17, 1),
        np.arange(4.5, 17, 1),
    ):
        proposals += 1
        cpu = np.array([x, y])
        ram = cpu.copy()
        ram[axis] += sign * (8.5 + g)
        ram[1 - axis] += t
        pair = np.stack([cpu, ram]) - 19.5
        quadrants = [pair]
        for _ in range(3):
            q = quadrants[-1]
            quadrants.append(np.stack([-q[:, 1], q[:, 0]], axis=1))
        ordered = np.array(quadrants)[[0, 1, 3, 2]] + 19.5
        xy = np.round(1000 * np.vstack((ordered[:, 0], ordered[:, 1])), 5)
        parity = [axis, 1 - axis, 1 - axis, axis]
        r = np.array(parity + [0] * 4) * 90
        if not is_legal(p, Layout(xy, r), 0):
            continue
        key = (tuple(xy.ravel()), tuple(parity))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            dict(
                id="rot-" + str(len(rows)),
                centres_um=xy.tolist(),
                parity=parity,
                base_c=None,
            )
        )
    return proposals, rows


def config_at(p, xy, row):
    size = sizes_mm(p, row["parity"])
    c = row["profiles"][NAME]
    r = np.array(c["rotation_deg"]) // 90
    mem = sum(
        STATE["costs"].length(i, i + 4, r[i], r[i + 4], *((xy[i + 4] - xy[i]) * 1000))
        / 1e6
        for i in range(4)
    )
    wire = mem
    maximum = 0.0
    for a, b in RING:
        cost, worst = edge_matrices(
            tuple(size[a]), tuple(size[b]), xy[b] - xy[a], PROFILES[NAME]
        )
        ij = (
            c["sides"][a][NEIGHBOURS[a].index(b)],
            c["sides"][b][NEIGHBOURS[b].index(a)],
        )
        wire += cost[ij]
        maximum = max(maximum, worst[ij])
    return dict(
        c,
        wire_m=float(wire),
        memory_m=float(mem),
        max_cpu_signal_mm=float(maximum),
        latency_ns=4.125 + float(maximum) / 150,
    )


def refine(job):
    row, ratio, variant = job
    best, success = move(row, CAP_M * ratio, variant, STATE)
    if best is None:
        return [], bool(success)
    xy = np.rint(best[1].reshape(8, 2) * 1000)
    cfg = row["profiles"][NAME]
    if not is_legal(STATE["p"], Layout(xy, np.array(cfg["rotation_deg"])), 0):
        return [], bool(success)
    new = dict(
        row,
        id=f"move-{row['id']}-{ratio}-{variant}",
        centres_um=xy.tolist(),
        base_c=None,
    )
    cfg = config_at(STATE["p"], xy / 1000, new)
    assert cfg["wire_m"] <= CAP_M * ratio and cfg["max_cpu_signal_mm"] <= 25
    moved = screen(new)
    rerouted = moved["profiles"][NAME]
    assert rerouted is not None and rerouted["wire_m"] <= cfg["wire_m"] + 1e-8
    out = [dict(moved, profiles={NAME: cfg})]
    if (
        cfg["sides"] != rerouted["sides"]
        and abs(cfg["wire_m"] - rerouted["wire_m"]) > 1e-9
    ):
        out.append(dict(moved, id=moved["id"] + "-ports"))
    return out, bool(success)


def choose(ordered, n, p):
    result = []
    seen = set()
    for row in ordered:
        # Same thermal core geometry can have different bank placements or DRAM-wire costs.
        xy = np.array(row["centres_um"]) / 1000
        key = thermal_key(
            xy, sizes_mm(p, row["parity"]), p.power_w, np.array(p.carrier_um) / 1000
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) == n:
            break
    return result


def read(path):
    return json.loads(path.read_text())


def compute_search(args, p):
    original = read(args.first / "geometry.json")["rows"]
    # Include both previously verified cool spots even though they exceed the primary wide-wire cap.
    margin = read(EVIDENCE / "case3-phy-population-v1.json")
    for tag, z in margin["witnesses"].items():
        if tag.endswith("/wide"):
            continue
        r = np.array(z["config"]["rotation_deg"])[:4] // 90 % 2
        original.append(
            dict(
                id="ref-" + tag.split("/")[0],
                parity=r.tolist(),
                centres_um=z["centres_um"],
                base_c=None,
            )
        )
    proposals, geom = families(p)
    cert = next(
        c["certificate"]
        for c in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if c["certificate"]["case"] == "Case3"
    )
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        rows = list(pool.map(screen, original + geom, chunksize=18))
        rows = [r for r in rows if r["profiles"][NAME]]
        jobs = []
        for ratio in FACTORS:
            # Include over-budget starts so that sliding from a colder topology can find the gate.
            pool_rows = [
                r for r in rows if r["profiles"][NAME]["wire_m"] <= ratio * CAP_M * 1.35
            ]
            orders = [
                (
                    sorted(
                        [r for r in pool_rows if r["base_c"] is not None],
                        key=lambda r: r["base_c"],
                    ),
                    14,
                ),
                (sorted(pool_rows, key=lambda r: r["score"]), 18),
                (
                    sorted(
                        [
                            r
                            for r in pool_rows
                            if r["profiles"][NAME]["wire_m"] <= ratio * CAP_M
                        ],
                        key=lambda r: r["score"],
                    ),
                    18,
                ),
            ]
            starts = {r["id"]: r for order, n in orders for r in choose(order, n, p)}
            jobs.extend((r, ratio, v) for r in starts.values() for v in (0, 1))
        print("geometries", len(rows), "move jobs", len(jobs), flush=True)
        successes = 0
        added = []
        for out, success in pool.map(refine, jobs, chunksize=1):
            added.extend(out)
            successes += int(success)
    rows.extend(added)
    selected = {}
    counts = []
    for ratio in FACTORS:
        valid = [r for r in rows if r["profiles"][NAME]["wire_m"] <= CAP_M * ratio]
        counts.append(len(valid))
        orders = [
            (sorted(valid, key=lambda r: r["score"]), 24),
            (
                sorted(
                    [r for r in valid if r["id"].startswith("move-")],
                    key=lambda r: r["score"],
                ),
                12,
            ),
            (
                sorted(
                    [r for r in valid if r["base_c"] is not None],
                    key=lambda r: r["base_c"],
                ),
                6,
            ),
            (
                sorted(
                    [r for r in valid if r["id"].startswith("rot-")],
                    key=lambda r: r["score"],
                ),
                8,
            ),
        ]
        for order, n in orders:
            for row in choose(order, n, p):
                selected[row["id"]] = row
    for r in selected.values():
        direct_check(p, np.array(r["centres_um"]), r["profiles"][NAME], PROFILES[NAME])
    return dict(
        case="Case3",
        fourfold_proposals=proposals,
        fourfold_legal=len(geom),
        raw_original=len(original),
        reachable_before_moves=len(rows) - len(added),
        move_jobs=len(jobs),
        converged_moves=successes,
        valid_move_outputs=len(added),
        budget_factors=FACTORS,
        budget_counts=counts,
        selected=list(selected.values()),
    )


def measure(job):
    row, g = job
    try:
        field, _, err = solve_field(STATE["p"], row, NAME, g, 1.0)
    except ValueError as exc:
        raise ValueError(f"FV failed for {row['id']} on grid {g}: {exc}") from exc
    return row["id"], g, dict(peak_c=float(np.nanmax(field)), energy_error_w=abs(err))


def set_problem(p):
    STATE["p"] = p


def compute_heat(args, p):
    search = args.output.parent / "search.json"
    rows = read(search)["selected"]
    with ProcessPoolExecutor(
        args.workers, initializer=set_problem, initargs=(p,)
    ) as pool:
        coarse = list(pool.map(measure, [(r, 64) for r in rows]))
        checks = {i: {g: c} for i, g, c in coarse}
        keep = set()
        for ratio in FACTORS:
            valid = [r for r in rows if r["profiles"][NAME]["wire_m"] <= CAP_M * ratio]
            ranked = sorted(valid, key=lambda r: checks[r["id"]][64]["peak_c"])
            keep.update(r["id"] for r in ranked[:5])
        # Every 64-grid full-rate point is checked at both finer grids for the inverse metric.
        keep.update(i for i, c in checks.items() if c[64]["peak_c"] <= 109)
        for i, g, c in pool.map(
            measure, [(r, g) for r in rows if r["id"] in keep for g in (96, 128)]
        ):
            checks[i][g] = c
    for r in rows:
        r["checks"] = checks[r["id"]]
    return dict(search_sha256=digest(search), rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["search", "heat"])
    for opt in ("data", "first", "output"):
        parser.add_argument("--" + opt, required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh output")
    prior = read(EVIDENCE / "case3-phy-codesign-v1.json")
    assert digest(args.first / "geometry.json") == prior["raw_sha256"]["geometry.json"]
    p, _, _ = inputs(args.data)
    result = (
        compute_search(args, p) if args.stage == "search" else compute_heat(args, p)
    )
    result["driver_sha256"] = digest(Path(__file__))
    result["moves_sha256"] = digest(Path(__file__).with_name("wide_floorplan_moves.py"))
    args.output.write_text(json.dumps(result, allow_nan=False) + "\n")
    print(
        "finished",
        args.stage,
        len(result.get("selected", result.get("rows", []))),
        flush=True,
    )


if __name__ == "__main__":
    main()
