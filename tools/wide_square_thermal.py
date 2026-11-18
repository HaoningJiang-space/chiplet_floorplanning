"""Refine span-limited rectangular controls, varying memory placement and the heated sides."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import permutations, product
import json
from pathlib import Path

import numpy as np
from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import (
    CAP_M,
    RING,
    STATES,
    NEIGHBOURS,
    PROFILES,
    direct_check,
    edge_matrices,
    memory_states,
    sizes_mm,
)
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from wide_span_layouts import measure

SIGNS = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]])
MIRROR = np.array([[0, 1, 2, 3], [2, 1, 0, 3], [0, 3, 2, 1], [2, 3, 0, 1]])
INDICES = {tuple(map(int, s)): i for i, s in enumerate(STATES)}


def options(width, parity):
    size = sizes_mm(STATE["p"], [parity] * 4)
    cpu = np.rint((19.5 + SIGNS * np.array([width, 47.312 - width]) / 2) * 1000) / 1000
    matrices = {
        (a, b): edge_matrices(
            tuple(size[a]), tuple(size[b]), cpu[b] - cpu[a], PROFILES["wide"]
        )
        for a, b in RING
    }
    patterns = []
    for horizontal, vertical in permutations(range(4), 2):
        sides = []
        for i in range(4):
            row = [
                horizontal if abs(cpu[j, 1] - cpu[i, 1]) < 1e-5 else vertical
                for j in NEIGHBOURS[i]
            ]
            sides.append(tuple(int(MIRROR[i, h]) for h in row))
        wire = 0.0
        reach = 0.0
        for a, b in RING:
            pair = sides[a][NEIGHBOURS[a].index(b)], sides[b][NEIGHBOURS[b].index(a)]
            c, m = matrices[a, b]
            wire += c[pair]
            reach = max(reach, m[pair])
        if reach <= 25 + 1e-10:
            patterns.append((sides, float(wire), float(reach)))
    return cpu, patterns


def positions(width):
    # Both opposing edge banks and fourfold placements were cold in the first stage.
    offsets = list(product((4.5, 5.5, 7.0), (12.0, 13.5, 14.5, 15.0)))
    offsets += list(product((13.5, 15.0), (0.0, 1.5, 3.0, 4.5)))
    offsets += list(
        product(
            (width / 2 - 8.5, width / 2, width / 2 + 8.5),
            (
                (47.312 - width) / 2 - 8.5,
                (47.312 - width) / 2,
                (47.312 - width) / 2 + 8.5,
            ),
        )
    )
    for x, y in offsets:
        yield SIGNS * np.array([x, y])
        yield np.array([[-x, -y], [y, -x], [-y, x], [x, y]])
        # Opposing edge pairs may use different inter-memory spacings.
        if x == 4.5 and y >= 13.5:
            yield np.array([[-x, -y], [x, -y], [-x - 2, y], [x + 2, y]])


def designs(job):
    width, parity = job
    p = STATE["p"]
    cpu, patterns = options(width, parity)
    out = {}
    for j, delta in enumerate(positions(width)):
        ram = np.rint((19.5 + delta) * 1000) / 1000
        xy = np.vstack([cpu, ram])
        if not is_legal(
            p, Layout(np.rint(xy * 1000), np.array([90 * parity] * 4 + [0] * 4)), 0
        ):
            continue
        # All four DRAMs carry the same heat. Choose the best memory matching for each heated-side pattern.
        cost_by_position = []
        turns_by_position = []
        for shift in range(4):
            trial = np.vstack([cpu, np.roll(ram, -shift, axis=0)])
            m, t = memory_states(trial, [parity] * 4, STATE["costs"])
            cost_by_position.append(m)
            turns_by_position.append(t)
        for sides, cpu_wire, reach in patterns:
            st = [INDICES[v] for v in sides]
            cost = np.array(
                [
                    [cost_by_position[(k - i) % 4][i, st[i]] for k in range(4)]
                    for i in range(4)
                ]
            )
            if not np.isfinite(cost).any(axis=1).all():
                continue
            best = min(
                permutations(range(4)),
                key=lambda perm: sum(cost[i, k] for i, k in enumerate(perm)),
            )
            mem = sum(cost[i, k] for i, k in enumerate(best))
            if not np.isfinite(mem):
                continue
            turns = (
                np.array(
                    [
                        turns_by_position[(k - i) % 4][i, st[i]]
                        for i, k in enumerate(best)
                    ]
                ).T.ravel()
                * 90
            )
            hot = tuple(sorted(map(tuple, ram))), tuple(tuple(sorted(s)) for s in sides)
            wire = mem + cpu_wire
            if hot in out and out[hot]["profiles"]["wide"]["wire_m"] <= wire:
                continue
            config = dict(
                wire_m=wire,
                memory_m=mem,
                sides=sides,
                max_cpu_signal_mm=reach,
                rotation_deg=turns.tolist(),
                latency_ns=4.125 + reach / 150,
            )
            out[hot] = dict(
                id=f"rect-{width}-{parity}-{j}-{sides[0][0]}-{sides[0][1]}",
                span_mm=float(np.ptp(cpu, axis=0).sum()),
                centres_um=np.rint(np.vstack([cpu, ram[list(best)]]) * 1000).tolist(),
                parity=[parity] * 4,
                profiles=dict(wide=config),
            )
    return list(out.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output file")
    p, _, _ = inputs(args.data)
    cert = next(
        x["certificate"]
        for x in json.loads((EVIDENCE / "global-heat-floor-v1.json").read_text())[
            "cases"
        ]
        if x["certificate"]["case"] == "Case3"
    )
    widths = np.unique(np.r_[np.arange(23.5, 31.01, 0.25), 29.656, 23.656])
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        rows = [
            r for group in pool.map(designs, product(widths, range(2))) for r in group
        ]
        print("coarse", len(rows), flush=True)
        checks = {
            r["id"]: {g: c}
            for r, (i, g, c) in zip(
                rows, pool.map(measure, [(r, 64) for r in rows], chunksize=4)
            )
            if r["id"] == i
        }
        assert len(checks) == len(rows)
        keep = set()
        for cap in (CAP_M, 50.0, 75.0, float("inf")):
            local = [r for r in rows if r["profiles"]["wide"]["wire_m"] <= cap]
            local.sort(key=lambda r: checks[r["id"]][64]["peak_c"])
            keep.update(r["id"] for r in local[:10])
        # Check every coarse candidate below the physical ceiling.
        keep.update(i for i, c in checks.items() if c[64]["peak_c"] <= 109)
        finalists = [r for r in rows if r["id"] in keep]
        for i, g, c in pool.map(
            measure, [(r, g) for r in finalists for g in (96, 128)], chunksize=2
        ):
            checks[i][g] = c
    for r in rows:
        r["checks"] = checks[r["id"]]
    for r in finalists:
        direct_check(
            p, np.array(r["centres_um"]), r["profiles"]["wide"], PROFILES["wide"]
        )
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                layouts=len(rows),
                fine=len(finalists),
                rows=rows,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    print("fine", len(finalists), flush=True)


if __name__ == "__main__":
    main()
