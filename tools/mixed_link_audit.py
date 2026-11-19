"""Check centered-pin nesting, greedy minimum link upgrades, and all rotations at named centres."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np
from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import CAP_M, NEIGHBOURS, RING, STATES, bank, sizes_mm
from chiplet_floorplanning.placement import Layout, is_legal
from chiplet_floorplanning.placement.geometry import rotate
from compare_wire_heat import digest
from mixed_link_experiment import ANCHORS, read
from mixed_phy import PROFILES_BY_BIT, BITS, configurations, pin_check, temperature

PORTS = np.array(list(product(range(len(STATES)), repeat=4)))
BASE_FLOOR_M = 16.62643433728


def all_ports(p, row):
    xy = np.array(row["centres_um"]) / 1000
    parity = row["parity"]
    sizes = sizes_mm(p, parity)
    memory = np.zeros(len(PORTS))
    for i in range(4):
        match = (p.pin_chip == i).any(axis=1) & (p.pin_chip == i + 4).any(axis=1)
        off = p.pin_offset_um[match].copy() / 1000
        rev = p.pin_chip[match, 0] != i
        off[rev] = off[rev, ::-1]
        options = np.full(12, np.inf)
        for turn in (parity[i], parity[i] + 2):
            src = xy[i] + rotate(off[:, 0], 90 * turn)
            best = min(
                abs(src - xy[i + 4] - rotate(off[:, 1], 90 * t)).sum() / 1000
                for t in range(4)
            )
            valid = (STATES != turn).all(axis=1)
            options[valid] = np.minimum(options[valid], best)
        memory += options[PORTS[:, i]]
    wire = np.empty((2, 4, len(PORTS)))
    longest = np.empty_like(wire)
    for e, (a, b) in enumerate(RING):
        for j, profile in enumerate(PROFILES_BY_BIT):
            w = np.empty((4, 4))
            reach = np.empty_like(w)
            for sa, sb in product(range(4), repeat=2):
                coords = []
                for i, s in ((a, sa), (b, sb)):
                    wide = bank(tuple(sizes[i]), s, PROFILES_BY_BIT[0])[0]
                    pts = bank(tuple(sizes[i]), s, profile)[0]
                    if j:
                        assert np.allclose(wide[88:264], pts, rtol=0, atol=1e-12)
                    coords.append(xy[i] + pts)
                lengths = abs(coords[1] - coords[0]).sum(axis=1)
                w[sa, sb] = lengths.sum() / 1000
                reach[sa, sb] = lengths.max()
            ix = (
                STATES[PORTS[:, a], NEIGHBOURS[a].index(b)],
                STATES[PORTS[:, b], NEIGHBOURS[b].index(a)],
            )
            wire[j, e], longest[j, e] = w[ix], reach[ix]
    assert (wire[0] >= wire[1] - 1e-9).all()
    required = longest[0] > 25 + 1e-10
    impossible = (longest[1] > 25 + 1e-10).any(axis=0)
    saved = wire[0] - wire[1]
    cost = memory + wire[0].sum(axis=0) - (saved * required).sum(axis=0)
    choices = required.sum(axis=0)
    ordered = np.sort(np.where(required, 0, saved), axis=0)[::-1]
    greedy = np.where(cost <= CAP_M + 1e-9, choices, 5)
    for count, delta in enumerate(ordered, start=1):
        cost = cost - delta
        greedy = np.minimum(greedy, np.where(cost <= CAP_M + 1e-9, choices + count, 5))
    greedy[impossible] = 5
    enum = np.full(len(PORTS), 5)
    masks = []
    for m in range(16):
        c = memory + wire[BITS[m], np.arange(4)].sum(axis=0)
        c = np.where(
            (longest[BITS[m], np.arange(4)] <= 25 + 1e-10).all(axis=0), c, np.inf
        )
        enum[c <= CAP_M + 1e-9] = np.minimum(enum[c <= CAP_M + 1e-9], m.bit_count())
        best = float(c.min())
        masks.append(best if np.isfinite(best) else None)
    assert np.array_equal(greedy, enum)
    return masks, dict(Counter(map(int, greedy)))


def decision(row):
    p = STATE["p"]
    xy = np.array(row["centres_um"])
    all_min = [None] * 16
    parities = 0
    histogram = Counter()
    matched = None
    for parity in product(range(2), repeat=4):
        if not is_legal(p, Layout(xy, np.array([*parity, 0, 0, 0, 0]) * 90), 0):
            continue
        parities += 1
        local = dict(row, parity=list(parity))
        brute, hist = all_ports(p, local)
        histogram.update(hist)
        cfs = configurations(p, local, STATE["costs"])
        for m, (v, c) in enumerate(zip(brute, cfs)):
            if v is None:
                assert c is None
                continue
            assert abs(v - c["wire_m"]) < 1e-8
            if all_min[m] is None or v < all_min[m]["wire_m"]:
                all_min[m] = dict(wire_m=v, parity=parity)
        if list(parity) == list(row["parity"]):
            matched = cfs
    assert matched is not None
    return dict(
        id=row["id"],
        legal_parities=parities,
        port_assignments=parities * len(PORTS),
        greedy_minimum_histogram=histogram,
        all_parity_min_by_mask=all_min,
        original_configs=matched,
    )


def choose_points(rows, heat, ref):
    catalogue = {r["id"]: r for r in rows}
    samples = []
    for r in heat["checks"]:
        if len(r["checks"]) == 3:
            samples.append(
                (
                    catalogue[r["id"]],
                    r["mask"],
                    r["wire_m"],
                    max(x["peak_c"] for x in r["checks"].values()),
                )
            )
    for r in ref["records"]:
        row = r["row"]
        catalogue[row["id"]] = row
        samples.append(
            (
                row,
                r["mask"],
                r["config"]["wire_m"],
                max(x["peak_c"] for x in r["checks"].values()),
            )
        )
    chosen = {f"anchor-{i}": i for i in ANCHORS}
    for k in range(5):
        group = [s for s in samples if s[1].bit_count() == k and s[2] <= CAP_M]
        if not group:
            continue
        best = min(group, key=lambda s: s[3])
        chosen[f"coldest-{k}"] = best[0]["id"]
        cold = [s for s in group if s[3] <= 109]
        if cold:
            chosen[f"shortest-{k}"] = min(cold, key=lambda s: s[2])[0]["id"]
            for tag, key in [
                ("largest", lambda s: -s[0]["joint_span_mm"]),
                ("coolest-matched", lambda s: s[3]),
            ]:
                matched = [s for s in cold if s[0]["necessary_fast"] == k]
                if matched:
                    chosen[f"{tag}-{k}"] = min(matched, key=key)[0]["id"]
    return chosen, {v: catalogue[v] for v in sorted(set(chosen.values()))}


def solve_grid(job):
    r, m, c, g = job
    return (r["id"], m), g, temperature(STATE["p"], r, m, c, g)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "output"):
        ap.add_argument("--" + k, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=15)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use fresh output")
    p, _, _ = inputs(args.data)
    files = [args.output.parent / (n + ".json") for n in ("geometry", "heat", "refine")]
    rows, heat, ref = (read(f) for f in files)
    floor = read(EVIDENCE / "case3-interface-cut-v1.json")["memory_floor_m"]
    assert abs(floor - BASE_FLOOR_M) < 1e-12
    slack = []
    for r in rows["rows"]:
        for m, c in enumerate(r["configs"]):
            if c:
                lb = (
                    floor
                    + 1.408 * r["clearance_mm"]
                    + max(0, 0.352 * (2 * r["span_mm"] - 31.2) - 4.4 * m.bit_count())
                )
                slack.append(c["wire_m"] - lb)
    assert min(slack) > -1e-7
    chosen, targets = choose_points(rows["rows"], heat, ref)
    cert = next(
        c["certificate"]
        for c in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if c["certificate"]["case"] == "Case3"
    )
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        records = list(pool.map(decision, targets.values()))
        checks = {}
        jobs = []
        for rec in records:
            row = targets[rec["id"]]
            for mask, cfg in enumerate(rec["original_configs"]):
                if cfg:
                    checks[row["id"], mask] = {}
                    jobs.extend((row, mask, cfg, g) for g in (64, 96, 128))
        for key, g, c in pool.map(solve_grid, jobs, chunksize=2):
            checks[key][g] = c
    for rec in records:
        row = targets[rec["id"]]
        rec["layout"] = {k: v for k, v in row.items() if k != "configs"}
        for mask, c in enumerate(rec["original_configs"]):
            if c:
                c["checks"] = checks[rec["id"], mask]
                c["pin_bundles"] = pin_check(p, row, mask, c)
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                raw_sha256={f.name: digest(f) for f in files},
                source_sha256=digest(Path(__file__).with_name("mixed_phy.py")),
                wire_bound_checks=len(slack),
                min_wire_slack_m=min(slack),
                chosen=chosen,
                full_checks=len(jobs),
                points=records,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    print(
        "audited",
        len(records),
        "port-state comparisons",
        sum(x["port_assignments"] for x in records),
        flush=True,
    )


if __name__ == "__main__":
    main()
