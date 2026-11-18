"""Place eight full-power dies at controlled CPU spans and measure both wire and temperature."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.special import k0
from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import CAP_M, PROFILES, direct_check
from case3_phy_thermal import solve_field
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from wide_floorplan import screen

# Round the primary span down at construction, then verify physical coordinates in microns.
SPANS = (40.0, 47.312, 56.0)
PAIRS = np.triu_indices(8, 1)


def rotate4(v):
    x, y = v.T
    return np.stack(
        [v, np.stack([-y, x], axis=1), np.stack([y, -x], axis=1), -v], axis=1
    )


def proposals(job):
    span, shape, amount, pattern = job
    p = STATE["p"]
    parity = (
        [pattern, 1 - pattern, 1 - pattern, pattern]
        if shape == "rot"
        else [pattern] * 4
    )
    sizes = np.array(
        [[9.0, 8.0] if h else [8.0, 9.0] for h in parity] + [[9.0, 9.0]] * 4
    )
    if shape == "rot":
        first = np.array([[-span / 4, -span / 4 * amount]])
        cpu = rotate4(first)[0]
    else:
        width = span / 2 + amount
        height = span - width
        cpu = (
            np.array(
                [[-width, -height], [width, -height], [-width, height], [width, height]]
            )
            / 2
        )
    cpu = np.rint(cpu * 1000) / 1000
    knots = np.unique(
        np.round(
            np.r_[
                np.arange(-15, 15.01, 1.5),
                cpu[0, 0] + np.array([-9, -8.5, -0.334, 0, 0.334, 8.5, 9]),
                cpu[0, 1] + np.array([-9, -8.5, -0.334, 0, 0.334, 8.5, 9]),
            ],
            3,
        )
    )
    knots = knots[abs(knots) <= 15]
    first = np.array(list(product(knots, repeat=2)))
    # Rotated and mirrored memory groups give tangential and radial pair attachments.
    groups = [rotate4(first)]
    if shape == "rect":
        groups.append(
            first[:, None, :] * np.array([[1, 1], [-1, 1], [1, -1], [-1, -1]])
        )
    xy = np.concatenate(
        [
            np.concatenate([np.broadcast_to(cpu, ram.shape), ram], axis=1)
            for ram in groups
        ]
    )
    valid = np.all(abs(xy) + sizes / 2 <= 19.500000001, axis=(1, 2))
    a, b = PAIRS
    valid &= np.all(
        np.any(abs(xy[:, a] - xy[:, b]) >= (sizes[a] + sizes[b]) / 2 - 1e-10, axis=2),
        axis=1,
    )
    xy = xy[valid]
    if not len(xy):
        return 0, []
    # Proxy ranks geometries only. The physical decision uses three full finite-volume solves.
    delta = xy[:, :, None, :] - xy[:, None, :, :]
    d2 = (
        (delta**2).sum(axis=3)
        + (sizes**2).sum(axis=1)[:, None] / 12
        + (sizes**2).sum(axis=1)[None, :] / 12
    )
    lam, w = STATE["radii"][-2:], STATE["weights"][-2:]
    mutual = k0(np.sqrt(d2)[..., None] / lam) @ w
    np.einsum("nii->ni", mutual)[:] = 0
    score = (mutual[:, :4] @ p.power_w).max(axis=1)
    distances = abs(xy[:, :4] - xy[:, 4:]).sum(axis=2)
    # Sample both remote DRAM for the span-only control and nearby DRAM for the wire gate.
    ids = set(np.argsort(score)[:14]) | set(
        np.lexsort((score, distances.sum(axis=1)))[:12]
    )
    for mx in (9, 12, 16, 22):
        possible = np.where(distances.max(axis=1) <= mx)[0]
        ids.update(possible[np.argsort(score[possible])[:4]])
    rows = []
    for j in sorted(ids):
        coord = np.rint((19.5 + xy[j]) * 1000)
        assert is_legal(p, Layout(coord, np.array(parity + [0] * 4) * 90), 0)
        actual = np.ptp(coord[:4], axis=0).sum() / 1000
        assert actual <= span + 0.00001
        row = screen(
            dict(
                id=f"{span}-{shape}-{amount}-{pattern}-{j}",
                span_limit_mm=span,
                span_mm=float(actual),
                centres_um=coord.tolist(),
                parity=parity,
            )
        )
        if row["profiles"]["wide"]:
            rows.append(row)
    return len(xy), rows


def measure(job):
    row, grid = job
    p = STATE["p"]
    field, _, err = solve_field(p, row, "wide", grid, 1.0)
    return (
        row["id"],
        grid,
        dict(peak_c=float(np.nanmax(field)), balance_error_w=abs(err)),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output path")
    p, _, _ = inputs(args.data)
    cert = next(
        x["certificate"]
        for x in json.loads((EVIDENCE / "global-heat-floor-v1.json").read_text())[
            "cases"
        ]
        if x["certificate"]["case"] == "Case3"
    )
    jobs = [
        (span, shape, v, h)
        for span in SPANS
        for h in range(2)
        for shape, vs in [
            ("rot", [-1, -0.85, -0.65, -0.45, 0, 0.45, 0.65, 0.85, 1]),
            ("rect", [0, 2, 4, 6]),
        ]
        for v in vs
    ]
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        parts = list(pool.map(proposals, jobs))
        # Preserve the established primary-budget and maximum-span controls.
        old = json.loads((EVIDENCE / "case3-interface-cut-v1.json").read_text())
        base = old["wide_budget_ladder"][0]["best"]
        spanrow = old["wide_span"]["layout"]
        sources = [r for _, rows in parts for r in rows]
        keys = set()
        rows = []
        for r in sources:
            key = (tuple(np.ravel(r["centres_um"])), tuple(r["parity"]))
            if key not in keys:
                rows.append(r)
                keys.add(key)
        for idx, coord, config in [
            ("prior-tight", base["centres_um"], base["config"]),
            ("prior-span", spanrow["centres_um"], spanrow["profiles"]["wide"]),
        ]:
            xy = np.array(coord)
            rows.append(
                dict(
                    id=idx,
                    span_mm=float(np.ptp(xy[:4], axis=0).sum() / 1000),
                    centres_um=coord,
                    parity=(np.array(config["rotation_deg"][:4]) // 90 % 2).tolist(),
                    profiles=dict(wide=config),
                )
            )
        print("actual coarse solves", len(rows), flush=True)
        checks = {}
        for idx, g, c in pool.map(measure, [(r, 64) for r in rows], chunksize=2):
            checks[idx] = {g: c}
        selected = set()
        for span in SPANS:
            for cap in (CAP_M, np.inf):
                group = [
                    r
                    for r in rows
                    if r["span_mm"] <= span + 1e-8
                    and r["profiles"]["wide"]["wire_m"] <= cap
                    and r["profiles"]["wide"]["latency_ns"] <= 5
                ]
                group.sort(key=lambda r: checks[r["id"]][64]["peak_c"])
                selected.update(r["id"] for r in group[:5])
                cold = [r for r in group if checks[r["id"]][64]["peak_c"] <= 109]
                selected.update(
                    r["id"]
                    for r in sorted(
                        cold, key=lambda r: r["profiles"]["wide"]["wire_m"]
                    )[:5]
                )
        short = [r for r in rows if r["id"] in selected]
        for idx, g, c in pool.map(measure, [(r, g) for r in short for g in (96, 128)]):
            checks[idx][g] = c
    for r in short:
        direct_check(
            p, np.array(r["centres_um"]), r["profiles"]["wide"], PROFILES["wide"]
        )
    for r in rows:
        r["checks"] = checks[r["id"]]
    result = dict(
        driver_sha256=digest(Path(__file__)),
        accepted_proposals=sum(n for n, _ in parts),
        tested=len(rows),
        three_grids=len(short),
        rows=rows,
    )
    args.output.write_text(json.dumps(result, allow_nan=False) + "\n")
    print("fine", len(short), flush=True)


if __name__ == "__main__":
    main()
