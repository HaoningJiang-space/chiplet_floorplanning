"""Evaluate the ring min-cut width prediction and the four-module, 16 GT/s alternative."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path
import json
import numpy as np

from case3_phy_experiment import EVIDENCE, inputs
from case3_phy_geometry import (
    CAP_M,
    RING,
    PROFILES,
    Interface,
    BundleLengths,
    bank,
    direct_check,
    memory_states,
    select_ports,
    sizes_mm,
)
from case3_phy_thermal import solve_field
from check_case3_phy_population import fourfold, geometry_key
from check_phy_route_margin import stretch, brute_wire
from compare_wire_heat import digest

MID = Interface(4, 16, 1.0, 1.32)
WORK = {}


def setup(p):
    PROFILES["mid"] = MID
    WORK.update(p=p, costs=BundleLengths(p))


def read(p):
    return json.loads(p.read_text())


def cut_constants(name):
    profile = PROFILES[name]
    pads, _ = bank((8.0, 9.0), 0, profile)
    n = len(pads)
    # Enumerate all nontrivial cuts, anchoring vertex zero to avoid duplicated complements.
    cut_counts = [
        sum(n for a, b in RING if mask[a] != mask[b])
        for tail in product(range(2), repeat=3)
        if any(tail)
        for mask in [(0, *tail)]
    ]
    radius = max(
        abs(bank(s, h, profile)[0].mean(axis=0)).sum()
        for s in ((8.0, 9.0), (9.0, 8.0))
        for h in range(4)
    )
    return n, min(cut_counts), 8 * radius


def stats(row, c, values, reserve):
    xy = np.array(row["centres_um"][:4]) / 1000
    s = float(np.ptp(xy, axis=0).sum())
    n, cut, correction = values
    centre = float(sum(abs(xy[a] - xy[b]).sum() for a, b in RING))
    assert n * centre >= cut * s - 1e-7
    lower = reserve + max(0.0, cut * s - n * correction) / 1000
    assert c["wire_m"] >= lower - 1e-8
    return float(c["wire_m"] - lower)


def geometry(row):
    p = WORK["p"]
    xy = np.array(row["centres_um"]) / 1000
    mem, turns = memory_states(xy, row["parity"], WORK["costs"])
    mid = select_ports(xy, sizes_mm(p, row["parity"]), mem, turns, MID)
    return dict(row, profiles={**row.get("profiles", {}), "mid": mid})


def measure(job):
    row, g = job
    field, _, err = solve_field(WORK["p"], row, "mid", g, 1.0)
    assert abs(err) < 1e-7
    return row["id"], g, dict(peak_c=float(np.nanmax(field)), energy_error_w=abs(err))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for opt in ("data", "first", "output"):
        ap.add_argument("--" + opt, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh file")
    p, _, _ = inputs(args.data)
    setup(p)
    prior = read(EVIDENCE / "case3-phy-population-v1.json")
    initial = read(EVIDENCE / "case3-phy-codesign-v1.json")
    assert (
        digest(args.first / "geometry.json") == initial["raw_sha256"]["geometry.json"]
    )
    orig = read(args.first / "geometry.json")["rows"]
    extra, _, _ = fourfold(p, orig)
    rows = orig + extra
    # The two prediction points are identified by coordinates as well as prior stable IDs.
    pred = [
        prior["groups"]["union"]["narrow"]["best_id"],
        prior["route_margin"]["winner_id"],
    ]
    seen = {geometry_key(r) for r in rows}
    search = args.output.parent / "search.json"
    for r in read(search)["selected"]:
        k = geometry_key(r)
        if k not in seen:
            rows.append(r)
            seen.add(k)
    reserve = (
        read(EVIDENCE / "case3-ring-certificate-v1.json")["heat_lower_bound"][
            "reserved_dram_bundle_sum_mm"
        ]
        / 1000
    )
    constants = {n: cut_constants(n) for n in PROFILES}
    with ProcessPoolExecutor(args.workers, initializer=setup, initargs=(p,)) as pool:
        rows = list(pool.map(geometry, rows, chunksize=16))
        lookup = {r["id"]: r for r in rows}
        valid = [
            r
            for r in rows
            if (c := r["profiles"]["mid"])
            and c["wire_m"] <= CAP_M
            and c["latency_ns"] <= 5
        ]
        wanted = {r["id"] for r in valid} | set(pred)
        jobs = [(lookup[i], 64) for i in sorted(wanted) if lookup[i]["profiles"]["mid"]]
        checks = {i: {g: v} for i, g, v in pool.map(measure, jobs, chunksize=3)}
        eligible = [r for r in valid if checks[r["id"]][64]["peak_c"] <= 109]
        ids = set(pred)
        orders = [
            sorted(valid, key=lambda r: checks[r["id"]][64]["peak_c"]),
            sorted(eligible, key=lambda r: r["profiles"]["mid"]["wire_m"]),
            sorted(eligible, key=lambda r: -stretch(r["profiles"]["mid"])),
        ]
        for order in orders:
            ids.update(r["id"] for r in order[:8])
        for i, g, v in pool.map(
            measure,
            [(lookup[i], g) for i in sorted(ids) if i in checks for g in (96, 128)],
        ):
            checks[i][g] = v
    residuals = {n: [] for n in constants}
    for row in rows:
        for n, c in row["profiles"].items():
            if c:
                residuals[n].append(stats(row, c, constants[n], reserve))
    points = []
    for i in sorted(ids):
        row = lookup[i]
        if i not in checks:
            assert row["profiles"]["mid"] is None
            points.append(dict(id=i, checks=None, config=None))
            continue
        c = row["profiles"]["mid"]
        direct_check(p, np.array(row["centres_um"]), c, MID)
        brute_wire(p, row, "mid")
        span = float(np.ptp(np.array(row["centres_um"][:4]) / 1000, axis=0).sum())
        points.append(
            dict(
                id=i,
                span_sum_mm=span,
                config=c,
                centres_um=row["centres_um"],
                checks=checks[i],
                feasible=c["wire_m"] <= CAP_M
                and c["latency_ns"] <= 5
                and max(v["peak_c"] for v in checks[i].values()) <= 109,
            )
        )
    out = dict(
        driver_sha256=digest(Path(__file__)),
        search_sha256=digest(search),
        memory_floor_m=reserve,
        mincut={
            n: dict(
                n_per_edge=vals[0],
                mincut_lines=vals[1],
                offset_sum_mm=vals[2],
                maximum_span_sum_mm=(1000 * (CAP_M - reserve) + vals[0] * vals[2])
                / vals[1],
                checks=len(residuals[n]),
                min_wire_minus_bound_m=min(residuals[n]),
            )
            for n, vals in constants.items()
        },
        predicted_ids=pred,
        geometries=len(rows),
        geometry_qualified=len(valid),
        full64=len(eligible),
        field_counts={g: sum(g in x for x in checks.values()) for g in (64, 96, 128)},
        points=points,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print(
        out["geometry_qualified"],
        out["full64"],
        [(p["id"], p.get("feasible")) for p in points if p["id"] in pred],
        flush=True,
    )


if __name__ == "__main__":
    main()
