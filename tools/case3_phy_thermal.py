"""Spatial PHY power, per-cell thermal headroom and matched-grid throughput checks."""

from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np

from case3_phy_geometry import (
    CAP_M,
    LIMIT_C,
    PAYLOAD_FRACTION,
    PROFILES,
    bank,
    direct_check,
    sizes_mm,
)
from chiplet_floorplanning.placement import Layout, solve, thermal_case_data
from compare_wire_heat import digest

WORK = {}


def setup(p, rows):
    WORK.update(p=p, rows={r["id"]: r for r in rows})


def thermal_input(p, row, name, grid, fraction):
    profile = PROFILES[name]
    config = row["profiles"][name]
    layout = Layout(np.array(row["centres_um"]), np.array(config["rotation_deg"]))
    data = thermal_case_data(p, layout, 0, grid)
    size = sizes_mm(p, row["parity"])
    for i, chip in enumerate(data["chiplets"][:4]):
        # Coordinates are now expressed in the world axes relative to the oriented die's corner.
        width, height = size[i]
        chip["rotation_deg"] = 0
        chip["size_mm"] = dict(width=width, height=height)
        rects = [
            np.round(
                bank(tuple(size[i]), side, profile)[1] + np.tile(size[i] / 2, 2), 9
            )
            for side in config["sides"][i]
        ]
        for rect in rects:
            assert np.all(rect[:2] >= -1e-12) and np.all(rect[2:] <= size[i] + 1e-12)
        assert np.any(
            np.minimum(rects[0][2:], rects[1][2:])
            <= np.maximum(rects[0][:2], rects[1][:2]) + 1e-12
        )
        xs = sorted({0.0, width, *[r[j] for r in rects for j in (0, 2)]})
        ys = sorted({0.0, height, *[r[j] for r in rects for j in (1, 3)]})
        blocks = []
        accounted = np.zeros(2)
        for (x, x1), (y, y1) in product(zip(xs, xs[1:]), zip(ys, ys[1:])):
            area = (x1 - x) * (y1 - y)
            cx, cy = (x + x1) / 2, (y + y1) / 2
            watts = area * p.power_w[i] / (width * height)
            for j, (ax, ay, bx, by) in enumerate(rects):
                if ax < cx < bx and ay < cy < by:
                    share = area / ((bx - ax) * (by - ay))
                    accounted[j] += share
                    watts += fraction * profile.full_phy_w * share / 8
            blocks.append(
                dict(
                    id="cell" + str(len(blocks)),
                    rect_mm=dict(x=x, y=y, width=x1 - x, height=y1 - y),
                    power_w=float(watts),
                    provenance="Uniform source core plus two localized synthesized PHY banks",
                )
            )
        assert np.allclose(accounted, 1.0)
        chip["blocks"] = blocks
    return data


def solve_field(p, row, name, grid, fraction):
    obs, rise, edges = solve(thermal_input(p, row, name, grid, fraction))
    assert (
        abs(obs["source_power_w"] - (680 + fraction * PROFILES[name].full_phy_w)) < 1e-7
    )
    return rise + 45, edges, float(obs["energy_balance_error_w"])


def thermal_limits(job):
    idx, name, grid = job
    row = WORK["rows"][idx]
    base, axes, b0 = solve_field(WORK["p"], row, name, grid, 0.0)
    full, faxes, b1 = solve_field(WORK["p"], row, name, grid, 1.0)
    assert all(np.array_equal(a, b) for a, b in zip(axes, faxes))
    valid = np.isfinite(base)
    assert np.array_equal(valid, np.isfinite(full))
    delta = full[valid] - base[valid]
    assert delta.min() > -1e-7
    responsive = delta > 1e-10
    allowed = (
        0.0
        if np.max(base[valid]) > LIMIT_C
        else float(np.min((LIMIT_C - base[valid][responsive]) / delta[responsive]))
    )
    return (
        idx,
        name,
        grid,
        dict(
            base_peak_c=float(base[valid].max()),
            full_peak_c=float(full[valid].max()),
            power_fraction=float(np.clip(allowed, 0, 1)),
            max_full_rate_energy_pj_bit=max(0.0, allowed)
            * PROFILES[name].energy_pj_bit,
            energy_error_w=max(abs(b0), abs(b1)),
        ),
    )


def utilisation(checks, idle_share):
    power = min(c["power_fraction"] for c in checks.values())
    return max(0.0, min(1.0, (power - idle_share) / (1 - idle_share)))


def operating_point(job):
    idx, name, grid, u = job
    row = WORK["rows"][idx]
    profile = PROFILES[name]
    fraction = 0.25 + 0.75 * u
    field, _, err = solve_field(WORK["p"], row, name, grid, fraction)
    peak = float(np.nanmax(field))
    if u > 0:
        assert peak <= LIMIT_C + 2e-6
    return (
        idx,
        name,
        grid,
        dict(peak_c=peak, energy_error_w=abs(err), phy_w=fraction * profile.full_phy_w),
    )


def ranked(rows, checks, name):
    entries = [
        (r["id"], r["profiles"][name])
        for r in rows
        if r["profiles"][name] and (r["id"], name) in checks
    ]
    legal = [
        (i, c)
        for i, c in entries
        if c["wire_m"] <= CAP_M + 1e-10 and c["latency_ns"] <= 5
    ]

    def peak(idx):
        return max(x["full_peak_c"] for x in checks[idx, name].values())

    best = sorted(
        legal,
        key=lambda t: (
            -utilisation(checks[t[0], name], 0.25),
            peak(t[0]),
            t[1]["wire_m"],
        ),
    )
    full = [
        (i, c) for i, c in legal if utilisation(checks[i, name], 0.25) >= 1.0 - 1e-10
    ]
    shortest = sorted(full, key=lambda t: t[1]["wire_m"])
    cold = sorted(legal, key=lambda t: (peak(t[0]), t[1]["wire_m"]))
    return [i for i, _ in best], [i for i, _ in shortest], [i for i, _ in cold]


def thermal(args, p):
    geometry = json.loads(args.geometry.read_text())
    source = Path(__file__).parent
    assert all(
        digest(source / f) == sha
        for f, sha in geometry["source_sha256"].items()
        if f in ("case3_phy_geometry.py", "case3_phy_experiment.py")
    )
    ids = {"reference"} | {i for group in geometry["selected"].values() for i in group}
    rows = [r for r in geometry["rows"] if r["id"] in ids]
    checks = {}
    fine = set()
    print("paired shortlist", len(rows), flush=True)
    with ProcessPoolExecutor(
        args.workers, initializer=setup, initargs=(p, rows)
    ) as pool:
        jobs = [
            (r["id"], name, 64)
            for r in rows
            for name in PROFILES
            if r["profiles"][name]
        ]
        for i, name, grid, obs in pool.map(thermal_limits, jobs):
            checks[i, name] = {grid: obs}
        fine_ids = {"reference"}
        for name in PROFILES:
            best, shortest, cold = ranked(rows, checks, name)
            fine_ids.update(best[:4] + shortest[:1] + cold[:1])
        fine = {(i, name) for i in fine_ids for name in PROFILES if (i, name) in checks}
        print("fine paired profiles", len(fine), flush=True)
        for i, name, grid, obs in pool.map(
            thermal_limits, [(i, n, g) for i, n in sorted(fine) for g in (96, 128)]
        ):
            checks[i, name][grid] = obs
        final_checks = {tag: checks[tag] for tag in fine}
        final = {}
        audit_ids = set()
        for name in PROFILES:
            best, shortest, cold = ranked(rows, final_checks, name)
            final[name] = dict(
                best=best[0] if best else None,
                shortest_full=shortest[0] if shortest else None,
                coolest_full_load=cold[0] if cold else None,
            )
            audit_ids.update((i, name) for i in final[name].values() if i)
        audits = {}
        for i, n, g, obs in pool.map(
            operating_point,
            [
                (i, n, g, utilisation(checks[i, n], 0.25))
                for i, n in sorted(audit_ids)
                for g in (64, 96, 128)
            ],
        ):
            audits.setdefault((i, n), {})[g] = obs
    out = []
    for row in rows:
        for name, profile in PROFILES.items():
            tag = row["id"], name
            if tag not in checks:
                continue
            u = {str(idle): utilisation(checks[tag], idle) for idle in (0.0, 0.25, 0.5)}
            direct_check(p, np.array(row["centres_um"]), row["profiles"][name], profile)
            out.append(
                dict(
                    id=row["id"],
                    profile=name,
                    centres_um=row["centres_um"],
                    config=row["profiles"][name],
                    checks=checks[tag],
                    utilisation=u,
                    nominal_payload_tb_s=u["0.25"]
                    * profile.raw_gbps
                    * PAYLOAD_FRACTION
                    / 8000,
                    operating_checks=audits.get(tag),
                    qualified_geometry=row["profiles"][name]["wire_m"] <= CAP_M
                    and row["profiles"][name]["latency_ns"] <= 5,
                )
            )
    return dict(
        geometry_sha256=digest(args.geometry),
        counts=geometry["counts"],
        distinct=geometry["distinct"],
        final=final,
        points=out,
        field_pair_counts={
            g: sum(g in c for c in checks.values()) for g in (64, 96, 128)
        },
        direct_operating_solves=sum(len(c) for c in audits.values()),
    )
