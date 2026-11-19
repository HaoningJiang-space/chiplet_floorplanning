"""Refine the ring coordinates near the reach-limited minimum number of faster links."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize
from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import CAP_M, RING, NEIGHBOURS, offset_table, sizes_mm
from check_case3_phy_population import geometry_key
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from mixed_link_experiment import geometry, measure, read
from mixed_phy import PROFILES_BY_BIT, BITS, pin_check
from wide_floorplan_moves import Assignment, field_and_grad


def rotational(p):
    rows = []
    parity = [1, 0, 0, 1]
    turn = 90 * np.array(parity + [0] * 4)
    for x, y, shift, g in product(
        np.arange(7.75, 11.76, 0.25),
        np.arange(4, 6.76, 0.125),
        (-1.0, -0.334, 0.0, 0.334, 1.0),
        (0.0, 0.15),
    ):
        pair = np.array([[x, y], [x + shift, y + 8.5 + g]]) - 19.5
        groups = [pair]
        for _ in range(3):
            prev = groups[-1]
            groups.append(np.column_stack((-prev[:, 1], prev[:, 0])))
        a = np.array(groups)[[0, 1, 3, 2]] + 19.5
        xy = np.rint(np.vstack([a[:, 0], a[:, 1]]) * 1000)
        if is_legal(p, Layout(xy, turn), 0):
            rows.append(
                dict(
                    id=f"orbit-{x}-{y}-{shift}-{g}",
                    centres_um=xy.tolist(),
                    parity=parity,
                )
            )
    return rows


def clearance(p, r, tag):
    xy = np.array(r["centres_um"])
    size = sizes_mm(p, r["parity"]) * 1000
    direction = xy[4:] - xy[:4]
    slack = abs(direction) - (size[:4] + size[4:]) / 2
    axis = slack.argmax(axis=1)
    result = []
    for um in (50, 100, 150, 225, 350, 550):
        for mask in (15, 6, 9):
            pts = xy.copy()
            for i, h in enumerate(axis):
                if mask >> i & 1:
                    pts[i + 4, h] += np.sign(direction[i, h]) * um
            if is_legal(p, Layout(pts, np.array(r["parity"] + [0] * 4) * 90), 0):
                result.append(
                    dict(
                        id=f"clear-{tag}-{um}-{mask}",
                        centres_um=pts.tolist(),
                        parity=r["parity"],
                    )
                )
    return result


def move(job):
    row, mask, enforce = job
    p = STATE["p"]
    xy = np.array(row["centres_um"]) / 1000
    cfg = row["configs"][mask]
    fixed = Assignment(
        p, dict(parity=row["parity"], profiles={"wide": cfg}), STATE["costs"]
    )
    for e, (a, b) in enumerate(RING):
        if BITS[mask, e]:
            sa, sb = (
                cfg["sides"][a][NEIGHBOURS[a].index(b)],
                cfg["sides"][b][NEIGHBOURS[b].index(a)],
            )
            v, prefix, support = offset_table(
                tuple(fixed.size[a]), tuple(fixed.size[b]), sa, sb, PROFILES_BY_BIT[1]
            )
            fixed.edges[e] = a, b, list(zip(v, prefix))
            fixed.reach[e] = a, b, support
    assert abs(fixed.wire(xy.ravel())[0] - cfg["wire_m"]) < 1e-7

    def proxy(x):
        return field_and_grad(
            x.reshape(8, 2),
            fixed.size,
            p.power_w,
            STATE["radii"],
            STATE["weights"],
            STATE["self_k"],
        )

    cons = [fixed.constraints(xy, 0)]
    if enforce:
        # This affine lower support of the convex S + 2G guarantees membership in the target span band.
        v = np.zeros((8, 2))
        for h in range(2):
            v[np.argmax(xy[:4, h]), h] += 1
            v[np.argmin(xy[:4, h]), h] -= 1
        delta = xy[4:] - xy[:4]
        half = (fixed.size[4:] + fixed.size[:4]) / 2
        w = 2 * np.where(abs(delta) > half, np.sign(delta), 0)
        v[4:] += w
        v[:4] -= w
        target = 47.314957544346605 + (mask.bit_count() - 1) * 6.25
        cons.append(
            LinearConstraint(v.ravel(), target + (abs(w) * half).sum() + 0.01, np.inf)
        )
    cons.append(
        dict(
            type="ineq",
            fun=lambda x: CAP_M - 0.02 - fixed.wire(x)[0],
            jac=lambda x: -fixed.wire(x)[1],
        )
    )
    bounds = Bounds((fixed.size / 2).ravel(), (39 - fixed.size / 2).ravel())
    result = minimize(
        proxy,
        xy.ravel(),
        jac=True,
        method="SLSQP",
        constraints=cons,
        bounds=bounds,
        options=dict(maxiter=100, ftol=1e-7),
    )
    pts = np.rint(result.x.reshape(8, 2) * 1000)
    if not is_legal(p, Layout(pts, np.array(cfg["rotation_deg"])), 0):
        return None
    return dict(
        id=f'move-{row["id"]}-{mask}-{enforce}',
        centres_um=pts.tolist(),
        parity=row["parity"],
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("data", "output"):
        ap.add_argument("--" + key, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output")
    p, _, _ = inputs(args.data)
    cert = next(
        x["certificate"]
        for x in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if x["certificate"]["case"] == "Case3"
    )
    gfile = args.output.parent / "geometry.json"
    hfile = args.output.parent / "heat.json"
    lookup = {r["id"]: r for r in read(gfile)["rows"]}
    old = read(hfile)["checks"]
    jobs = set()
    seeds = set()
    for k in (1, 2, 3):
        for n in (k - 1, k):
            rank = sorted(
                (
                    r
                    for r in old
                    if r["mask"].bit_count() == k
                    and r["necessary_fast"] == n
                    and r["wire_m"] <= CAP_M
                ),
                key=lambda r: r["checks"]["64"]["peak_c"],
            )
            seen = set()
            for c in rank:
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                seeds.add(c["id"])
                jobs.add((c["id"], c["mask"], False))
                jobs.add((c["id"], c["mask"], True))
                for e in range(4):
                    m = c["mask"] & ~(1 << e)
                    cf = lookup[c["id"]]["configs"][m]
                    if m and m != c["mask"] and cf and cf["wire_m"] <= 56:
                        jobs.add((c["id"], m, False))
                if len(seen) == 10:
                    break
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        moves = list(
            pool.map(move, [(lookup[i], m, flag) for i, m, flag in sorted(jobs)])
        )
        candidates = [*rotational(p), *(r for r in moves if r)]
        for i in sorted(seeds):
            candidates.extend(clearance(p, lookup[i], i))
        distinct = {}
        for r in candidates:
            distinct.setdefault(geometry_key(r), r)
        rows = list(pool.map(geometry, distinct.values(), chunksize=10))
        groups = defaultdict(list)
        for i, r in enumerate(rows):
            for mask, c in enumerate(r["configs"]):
                k = mask.bit_count()
                if 0 < k < 4 and c and c["wire_m"] <= CAP_M and c["latency_ns"] <= 5:
                    groups[mask, r["necessary_fast"]].append(i)
        selected = set()
        for (mask, n), ids in groups.items():
            ranked = sorted(ids, key=lambda i: rows[i]["score"])
            top = (
                ranked[:80]
                + sorted(ids, key=lambda i: rows[i]["configs"][mask]["wire_m"])[:16]
            )
            top.extend(i for i in ranked if rows[i]["id"].startswith("move-"))
            for prefix in ("clear-", "orbit-"):
                top.extend([i for i in ranked if rows[i]["id"].startswith(prefix)][:25])
            selected.update((i, mask) for i in top)
        print(
            "geometry",
            len(rows),
            "moves",
            len(jobs),
            "coarse",
            len(selected),
            flush=True,
        )
        checks = {}
        for key, g, c in pool.map(
            measure, [(rows[i], m, 64) for i, m in sorted(selected)], chunksize=3
        ):
            checks[key] = {g: c}
        keep = set()
        fine_groups = defaultdict(list)
        for i, m in selected:
            fine_groups[m.bit_count(), rows[i]["necessary_fast"]].append((i, m))
        for pairs in fine_groups.values():
            coarse = lambda pair: checks[rows[pair[0]]["id"], pair[1]][64]["peak_c"]
            keep.update(sorted(pairs, key=coarse)[:15])
            cold = [pair for pair in pairs if coarse(pair) <= 109]
            keep.update(
                sorted(cold, key=lambda t: rows[t[0]]["configs"][t[1]]["wire_m"])[:10]
            )
            keep.update(sorted(cold, key=lambda t: -rows[t[0]]["joint_span_mm"])[:10])
        for key, g, c in pool.map(
            measure, [(rows[i], m, g) for i, m in sorted(keep) for g in (96, 128)]
        ):
            checks[key][g] = c
    records = []
    for i, m in sorted(keep):
        r = rows[i]
        cfg = r["configs"][m]
        records.append(
            dict(
                row={k: v for k, v in r.items() if k != "configs"},
                mask=m,
                config=cfg,
                checks=checks[r["id"], m],
                bundles=pin_check(p, r, m, cfg),
            )
        )
    out = dict(
        driver_sha256=digest(Path(__file__)),
        physics_sha256=digest(Path(__file__).with_name("mixed_phy.py")),
        raw_sha256={f.name: digest(f) for f in (gfile, hfile)},
        motion_jobs=len(jobs),
        move_legal=sum(r is not None for r in moves),
        unique=len(rows),
        coarse=len(selected),
        fine=len(records),
        records=records,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print("fine", len(records), flush=True)


if __name__ == "__main__":
    main()
