"""Search the four-edge equal-bandwidth link portfolio over shared archived and asymmetric floorplans."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np

from case3_phy_experiment import EVIDENCE, STATE, setup_geometry, inputs
from case3_phy_geometry import (
    CAP_M,
    PROFILES,
    heat_score,
    sizes_mm,
    select_ports,
    memory_states,
)
from check_case3_phy_population import fourfold, geometry_key
from check_interface_cut import MID
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from mixed_phy import configurations, temperature, pin_check, exhaustive_wire

ANCHORS = ("q-18-11-0--2", "q-15-9-0--2", "q-18-11-0-0")
SIGNS = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]])


def read(path):
    return json.loads(path.read_text())


def population(p, data):
    init = data / "case3-phy-b098fd9-r1/geometry.json"
    improved = data / "wide-continuous-f23b0a0-um/search.json"
    assert (
        digest(init)
        == read(EVIDENCE / "case3-phy-codesign-v1.json")["raw_sha256"]["geometry.json"]
    )
    assert (
        digest(improved)
        == read(EVIDENCE / "case3-interface-cut-v1.json")["raw_sha256"]["search.json"]
    )
    base = read(init)["rows"]
    extra, _, _ = fourfold(p, base)
    geometry = {}

    def add(r):
        entry = {k: r[k] for k in ("id", "centres_um", "parity")}
        geometry.setdefault(geometry_key(entry), entry)

    for r in base + extra + read(improved)["selected"]:
        add(r)
    counts = {"prior_unique": len(geometry)}
    anchors = read(EVIDENCE / "case3-interface-cut-v1.json")["mid_points"]
    for idx, r in anchors.items():
        xy = np.array(r["centres_um"])
        parity = (np.array(r["config"]["rotation_deg"][:4]) // 90 % 2).tolist()
        for dx, dy, t in product(range(-3, 4), range(-3, 4), (-2, 0, 2)):
            displacement = SIGNS * np.array([dx, dy]) * 1000
            displacement[[0, 1], 0] += t * 1000
            pts = xy + np.vstack([displacement, displacement])
            if is_legal(p, Layout(pts, np.array(parity + [0] * 4) * 90), 0):
                add(
                    dict(
                        id=f"shift-{idx}-{dx}-{dy}-{t}",
                        centres_um=pts.tolist(),
                        parity=parity,
                    )
                )
    counts["after_shifts"] = len(geometry)
    for w, h in product(range(20, 32), repeat=2):
        cpu = 19.5 + SIGNS * [w / 2, h / 2]
        for axes in product(range(2), repeat=4):
            parity = list(axes)
            for shift in (-1.5, 0.0, 1.5):
                ram = cpu.copy()
                for i, axis in enumerate(axes):
                    ram[i, axis] -= SIGNS[i, axis] * 8.5
                    ram[i, 1 - axis] += SIGNS[i, 1 - axis] * shift
                xy = np.rint(np.vstack([cpu, ram]) * 1000)
                if is_legal(p, Layout(xy, np.array(parity + [0] * 4) * 90), 0):
                    add(
                        dict(
                            id=f"rect-{w}-{h}-" + "".join(map(str, axes)) + f"-{shift}",
                            centres_um=xy.tolist(),
                            parity=parity,
                        )
                    )
    counts["total_unique"] = len(geometry)
    return (
        list(geometry.values()),
        counts,
        {f.name: digest(f) for f in (init, improved)},
    )


def geometry(row):
    p = STATE["p"]
    xy = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    span = float(np.ptp(xy[:4], axis=0).sum())
    gap = float(np.maximum(abs(xy[:4] - xy[4:]) - (size[:4] + size[4:]) / 2, 0).sum())
    bound = 47.314957544346605
    min_fast = max(0, int(np.ceil((span + 2 * gap - bound - 1e-8) / 6.25)))
    configs = configurations(p, row, STATE["costs"])
    for mask, c in enumerate(configs):
        if c and c["wire_m"] <= CAP_M:
            assert mask.bit_count() >= min_fast
    if row["id"] in ANCHORS:
        mem, turn = memory_states(xy, row["parity"], STATE["costs"])
        for mask, profile in ((0, PROFILES["wide"]), (15, MID)):
            old = select_ports(xy, size, mem, turn, profile)
            assert abs(old["wire_m"] - configs[mask]["wire_m"]) < 1e-8
        for mask, c in enumerate(configs):
            if c:
                pin_check(p, row, mask, c)
                assert abs(exhaustive_wire(p, row, mask) - c["wire_m"]) < 1e-8
    return dict(
        row,
        span_mm=span,
        clearance_mm=gap,
        joint_span_mm=span + 2 * gap,
        necessary_fast=min_fast,
        score=float(
            heat_score(
                xy, size, p.power_w, STATE["radii"], STATE["weights"], STATE["self_k"]
            )
        ),
        configs=configs,
    )


def measure(job):
    row, mask, g = job
    return (
        (row["id"], mask),
        g,
        temperature(STATE["p"], row, mask, row["configs"][mask], g),
    )


def choose(rows):
    by_group = defaultdict(list)
    selected = set()
    for i, r in enumerate(rows):
        for mask, c in enumerate(r["configs"]):
            if not c:
                continue
            if r["id"] in ANCHORS:
                selected.add((i, mask))
            if c["wire_m"] <= CAP_M and c["latency_ns"] <= 5:
                by_group[mask.bit_count(), r["necessary_fast"]].append((i, mask))
    for (k, _), pairs in by_group.items():
        if k <= 1:
            selected.update(pairs)
            continue
        for mask in sorted({m for _, m in pairs}):
            group = [x for x in pairs if x[1] == mask]
            wire = lambda x: rows[x[0]]["configs"][mask]["wire_m"]
            score = lambda x: rows[x[0]]["score"]
            selected.update(sorted(group, key=lambda x: (score(x), wire(x)))[:55])
            selected.update(sorted(group, key=lambda x: (wire(x), score(x)))[:24])
            selected.update(
                sorted(group, key=lambda x: (-rows[x[0]]["joint_span_mm"], score(x)))[
                    :12
                ]
            )
    return sorted(selected), {
        f"{k}/{n}": len(v) for (k, n), v in sorted(by_group.items())
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["geometry", "heat"])
    for key in ("data", "output"):
        ap.add_argument("--" + key, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output path")
    p, _, _ = inputs(args.data)
    cert = next(
        x["certificate"]
        for x in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if x["certificate"]["case"] == "Case3"
    )
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        if args.stage == "geometry":
            rows, counts, hashes = population(p, args.data)
            print("geometries", counts, flush=True)
            rows = list(pool.map(geometry, rows, chunksize=7))
            out = dict(inputs=hashes, counts=counts, rows=rows)
        else:
            source = args.output.parent / "geometry.json"
            rows = read(source)["rows"]
            pairs, counts = choose(rows)
            print("coarse", len(pairs), "geometry-gate", counts, flush=True)
            checks = {}
            for key, g, c in pool.map(
                measure, [(rows[i], mask, 64) for i, mask in pairs], chunksize=3
            ):
                checks[key] = {g: c}
            keep = set()
            buckets = defaultdict(list)
            for i, mask in pairs:
                r = rows[i]
                k = (r["id"], mask)
                if r["id"] in ANCHORS:
                    keep.add((i, mask))
                if r["configs"][mask]["wire_m"] <= CAP_M:
                    buckets[mask.bit_count(), r["necessary_fast"]].append((i, mask))
            for pairlist in buckets.values():
                get_temp = lambda im: checks[rows[im[0]]["id"], im[1]][64]["peak_c"]
                keep.update(sorted(pairlist, key=get_temp)[:5])
                cold = [x for x in pairlist if get_temp(x) <= 109]
                keep.update(
                    sorted(cold, key=lambda x: rows[x[0]]["configs"][x[1]]["wire_m"])[
                        :6
                    ]
                )
                keep.update(
                    sorted(cold, key=lambda x: -rows[x[0]]["joint_span_mm"])[:6]
                )
            for key, g, c in pool.map(
                measure,
                [(rows[i], mask, g) for i, mask in sorted(keep) for g in (96, 128)],
                chunksize=2,
            ):
                checks[key][g] = c
            summary = []
            for i, mask in pairs:
                r = rows[i]
                c = checks[r["id"], mask]
                summary.append(
                    dict(
                        id=r["id"],
                        mask=mask,
                        checks=c,
                        wire_m=r["configs"][mask]["wire_m"],
                        joint_span_mm=r["joint_span_mm"],
                        necessary_fast=r["necessary_fast"],
                    )
                )
            out = dict(
                geometry_sha256=digest(source),
                eligible_geometry=counts,
                coarse=len(pairs),
                fine=len(keep),
                checks=summary,
            )
    out["driver_sha256"] = digest(Path(__file__))
    out["physics_sha256"] = digest(Path(__file__).with_name("mixed_phy.py"))
    args.output.write_text(
        json.dumps(out, allow_nan=False, separators=(",", ":")) + "\n"
    )
    print("finished", args.stage, flush=True)


if __name__ == "__main__":
    main()
