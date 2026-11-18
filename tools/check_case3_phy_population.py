"""Check the complete registered populations at the common three-grid throughput gate."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np

from case3_phy_experiment import inputs, screen, setup_geometry, EVIDENCE
from case3_phy_geometry import CAP_M, PAYLOAD_FRACTION, PROFILES, direct_check
from case3_phy_thermal import (
    setup,
    WORK,
    solve_field,
    thermal_limits,
    utilisation,
    operating_point,
)
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest


def read(path):
    return json.loads(path.read_text())


def geometry_key(row):
    return tuple(np.asarray(row["centres_um"]).ravel()), tuple(row["parity"])


def fourfold(p, initial):
    # Start at SW; quarter turns produce SE, NE, NW. Store in source CPU order.
    seen = {geometry_key(r): r["id"] for r in initial}
    rows, members = [], []
    legal = 0
    for x, y, gap, shift in product(
        np.arange(4.5, 11, 0.5), np.arange(4, 10.5, 0.5), range(5), range(-2, 3)
    ):
        cpu = np.array([x, y])
        pair = np.array([cpu, cpu + [shift, 8.5 + gap]]) - 19.5
        quadrants = [pair]
        for _ in range(3):
            q = quadrants[-1]
            quadrants.append(np.stack([-q[:, 1], q[:, 0]], axis=1))
        ordered = np.array(quadrants)[[0, 1, 3, 2]] + 19.5
        xy = 1000 * np.vstack((ordered[:, 0], ordered[:, 1]))
        turns = np.array([90, 180, 0, 270, 0, 0, 0, 0])
        if not is_legal(p, Layout(xy, turns), 0):
            continue
        legal += 1
        row = dict(
            id=f"q-{int(2*x)}-{int(2*y)}-{gap}-{shift}",
            centres_um=xy.tolist(),
            parity=(1, 0, 0, 1),
            base_c=None,
        )
        key = geometry_key(row)
        if key not in seen:
            rows.append(row)
            seen[key] = row["id"]
        members.append(seen[key])
    return rows, set(members), legal


def check64(job):
    idx, name = job
    row = WORK["rows"][idx]
    field, _, err = solve_field(WORK["p"], row, name, 64, 0.0)
    peak = float(np.nanmax(field))
    if peak > 109:
        return (
            idx,
            name,
            64,
            dict(
                base_peak_c=peak,
                power_fraction=0.0,
                energy_error_w=abs(err),
                zero_phy_exclusion=True,
            ),
        )
    return thermal_limits((idx, name, 64))


def best_in_population(tags, checks, pool):
    if not tags:
        return None, 0.0, 0

    def value(t):
        return utilisation(checks[t], 0.25)

    known = [t for t in tags if len(checks[t]) == 3]
    best = max(known, key=value, default=None)
    lower = value(best) if best else 0.0
    remaining = sorted(
        (t for t in tags if len(checks[t]) < 3),
        key=lambda t: (-value(t), checks[t][64]["base_peak_c"], t),
    )
    at = 0
    while at < len(remaining) and value(remaining[at]) > lower + 1e-12:
        batch = []
        for tag in remaining[at : at + 14]:
            if value(tag) > lower + 1e-12:
                batch.append(tag)
        at += len(batch)
        jobs = [(i, n, grid) for i, n in batch for grid in (96, 128)]
        for i, n, grid, o in pool.map(thermal_limits, jobs):
            checks[i, n][grid] = o
        for t in batch:
            if value(t) > lower:
                lower = value(t)
                best = t
    upper = max(value(t) for t in tags)
    assert upper <= lower + 1e-12
    return best if lower > 0 else None, lower, upper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", default=14, type=int)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh output file")
    prior = read(EVIDENCE / "case3-phy-codesign-v1.json")
    for fn, sha in prior["raw_sha256"].items():
        assert digest(args.first / fn) == sha
    for fn, sha in prior["source_sha256"].items():
        assert digest(Path(__file__).with_name(fn)) == sha
    first = read(args.first / "geometry.json")
    hot = read(args.first / "thermal.json")
    p, _, _ = inputs(args.data)
    original = first["rows"]
    new, quad, legal = fourfold(p, original)
    cert = next(
        x["certificate"]
        for x in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if x["certificate"]["case"] == "Case3"
    )
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        extra = list(pool.map(screen, new, chunksize=12))
    rows = original + extra
    indexed = {r["id"]: r for r in rows}
    tags = {
        (r["id"], n)
        for r in rows
        for n, c in r["profiles"].items()
        if c and c["wire_m"] <= CAP_M and c["latency_ns"] <= 5.0
    }
    checks = {
        (p["id"], p["profile"]): {int(k): v for k, v in p["checks"].items()}
        for p in hot["points"]
        if (p["id"], p["profile"]) in tags
    }
    cached = set(checks)
    print(
        "geometry prepared",
        len(original),
        len(new),
        len(tags),
        "cached",
        len(cached),
        flush=True,
    )
    results = {}
    points = {}
    full_audits = {}
    with ProcessPoolExecutor(
        args.workers, initializer=setup, initargs=(p, rows)
    ) as pool:
        for i, n, grid, obs in pool.map(check64, sorted(tags - cached), chunksize=3):
            checks[i, n] = {grid: obs}
        print("all geometry-qualified configurations have 64-grid checks", flush=True)
        groups = {
            "original": {r["id"] for r in original},
            "fourfold": quad,
            "union": set(indexed),
        }
        for key, ids in groups.items():
            results[key] = {}
            for name, profile in PROFILES.items():
                subset = sorted(t for t in tags if t[0] in ids and t[1] == name)
                best, lower, upper = best_in_population(subset, checks, pool)
                results[key][name] = dict(
                    geometries=len(ids),
                    geometry_qualified=len(subset),
                    best_id=best[0] if best else None,
                    positive_64=sum(
                        checks[t][64]["power_fraction"] > 0.25 for t in subset
                    ),
                    minimum_zero_phy_peak_64_c=min(
                        (checks[t][64]["base_peak_c"] for t in subset), default=None
                    ),
                    utilisation_lower=lower,
                    utilisation_upper=upper,
                    payload_tb_s=lower * profile.raw_gbps * PAYLOAD_FRACTION / 8000,
                )
                print(key, name, results[key][name], flush=True)
                if best:
                    i, n = best
                    point_key = f"{i}/{n}"
                    if point_key not in points:
                        row = indexed[i]
                        direct_check(
                            p,
                            np.array(row["centres_um"]),
                            row["profiles"][name],
                            profile,
                        )
                        op = {
                            grid: obs
                            for _, _, grid, obs in pool.map(
                                operating_point,
                                [(i, n, g, lower) for g in (64, 96, 128)],
                            )
                        }
                        points[point_key] = dict(
                            centres_um=row["centres_um"],
                            config=row["profiles"][name],
                            checks=checks[best],
                            operating=op,
                            utilisation=lower,
                        )
        # Shared physical placement with each profile's own optimal port/routing choice.
        for n, r in results["union"].items():
            i = r["best_id"]
            if i:
                row = indexed[i]
                for label, profile in PROFILES.items():
                    cfg = row["profiles"][label]
                    if cfg:
                        direct_check(p, np.array(row["centres_um"]), cfg, profile)
                        temp = {
                            g: o
                            for _, _, g, o in pool.map(
                                thermal_limits, [(i, label, g) for g in (64, 96, 128)]
                            )
                        }
                        full_audits[f"{i}/{label}"] = dict(config=cfg, checks=temp)
    raw_checks = [dict(id=i, profile=n, checks=checks[i, n]) for i, n in sorted(tags)]
    out = dict(
        source_sha256=digest(Path(__file__)),
        quad_proposals=4225,
        quad_legal=legal,
        new_geometries=len(extra),
        results=results,
        points=points,
        paired=full_audits,
        cached_configurations=len(cached),
        checks=raw_checks,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
