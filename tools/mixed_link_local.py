"""Evaluate measured thermal moves around the best two-fast-edge configuration."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json

import numpy as np
from scipy.stats import qmc
from case3_phy_experiment import inputs
from case3_phy_geometry import (
    BundleLengths,
    CAP_M,
    RING,
    NEIGHBOURS,
    offset_table,
    sizes_mm,
)
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from mixed_phy import (
    BITS,
    PROFILES_BY_BIT,
    temperature,
    pin_check,
    exhaustive_wire,
    configurations,
)

STATE = {}


def setup(p, row, mask, cfg):
    STATE.update(p=p, row=row, mask=mask, cfg=cfg, costs=BundleLengths(p))


def coordinates(base, samples):
    """Maintain opposite CPU/memory pairs under a half turn, with independent shifts of the two representatives."""
    n = len(samples)
    v = np.broadcast_to(base, (n, 8, 2)).copy()
    for i in range(2):
        v[:, i, :] += samples[:, 2 * i : 2 * i + 2]
        v[:, i + 4, :] += samples[:, 2 * i : 2 * i + 2]
    # CPU 0's DRAM faces north, CPU 1's faces west in this frozen placement.
    v[:, 4, 0] += samples[:, 4]
    v[:, 5, 1] += samples[:, 5]
    v[:, 4, 1] += samples[:, 6]
    v[:, 5, 0] -= samples[:, 7]
    v[:, 2:4] = 39 - v[:, 1::-1]
    v[:, 6:8] = 39 - v[:, 5:3:-1]
    return np.rint(v * 1000) / 1000


def filter_geometry(p, row, mask, cfg, xy, costs):
    size = sizes_mm(p, row["parity"])
    valid = np.all(
        (xy >= size / 2 - 1e-10) & (xy <= 39 - size / 2 + 1e-10), axis=(1, 2)
    )
    a, b = np.triu_indices(8, 1)
    valid &= np.all(
        np.any(abs(xy[:, a] - xy[:, b]) >= (size[a] + size[b]) / 2 - 1e-10, axis=2),
        axis=1,
    )
    xy = xy[valid]
    turns = np.array(cfg["rotation_deg"]) // 90
    mem = np.zeros(len(xy))
    cpu = np.zeros(len(xy))
    longest = np.zeros(len(xy))

    def wire(axis, d):
        v, pref = axis
        k = np.searchsorted(v, d)
        return (2 * k - len(v)) * d + pref[-1] - 2 * pref[k]

    for i in range(4):
        delta = (xy[:, i + 4] - xy[:, i]) * 1000
        for h, axis in enumerate(costs.data[i, i + 4, turns[i], turns[i + 4]]):
            mem += wire(axis, delta[:, h]) / 1e6
    for e, (i, j) in enumerate(RING):
        si, sj = (
            cfg["sides"][i][NEIGHBOURS[i].index(j)],
            cfg["sides"][j][NEIGHBOURS[j].index(i)],
        )
        v, pre, support = offset_table(
            tuple(size[i]), tuple(size[j]), si, sj, PROFILES_BY_BIT[BITS[mask, e]]
        )
        delta = xy[:, j] - xy[:, i]
        for h, axis in enumerate(zip(v, pre)):
            cpu += wire(axis, delta[:, h]) / 1000
        for s, (sx, sy) in zip(support, ((1, 1), (1, -1), (-1, 1), (-1, -1))):
            longest = np.maximum(longest, s - sx * delta[:, 0] - sy * delta[:, 1])
    keep = (mem + cpu <= CAP_M) & (longest <= 25 + 1e-10)
    return xy[keep], np.column_stack((mem + cpu, mem, longest))[keep]


def field(job):
    xy, measure, g = job
    row = dict(STATE["row"], centres_um=np.rint(xy * 1000).tolist())
    cfg = dict(
        STATE["cfg"],
        wire_m=measure[0],
        memory_m=measure[1],
        max_cpu_signal_mm=measure[2],
        latency_ns=4.125 + measure[2] / 150,
    )
    return temperature(
        STATE["p"],
        row,
        STATE["mask"],
        cfg,
        g,
        node_limit=450_000 if g >= 160 else 250_000,
    )


def solve_set(pool, xy, metrics, grid):
    return list(
        pool.map(field, [(p, m, grid) for p, m in zip(xy, metrics)], chunksize=4)
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "output"):
        ap.add_argument("--" + k, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output")
    p, _, _ = inputs(args.data)
    source = args.output.parent / "refine.json"
    records = json.loads(source.read_text())["records"]
    seed = min(
        (r for r in records if r["mask"].bit_count() == 2),
        key=lambda r: max(c["peak_c"] for c in r["checks"].values()),
    )
    row, mask, cfg = seed["row"], seed["mask"], seed["config"]
    assert row["parity"] == [1, 0, 0, 1] and mask == 9
    base = np.array(row["centres_um"]) / 1000
    costs = BundleLengths(p)
    control, met = filter_geometry(p, row, mask, cfg, base[None], costs)
    assert len(control) == 1 and abs(met[0, 0] - cfg["wire_m"]) < 1e-8
    # Independent coordinates and correlated changes along an active reach constraint.
    sampler = qmc.Sobol(8, scramble=False)
    unit = 2 * sampler.random_base2(15) - 1
    rng = np.random.default_rng(73)
    scales = (0.08, 0.22, 0.55, 1.2, 2.2)
    with ProcessPoolExecutor(
        args.workers, initializer=setup, initargs=(p, row, mask, cfg)
    ) as pool:
        all_xy = []
        all_metrics = []
        all_fields = []
        summaries = []
        current = base
        for step in range(6):
            proposed = 0
            legal_count = 0
            parts = []
            for scale in scales if step == 0 else (0.03, 0.09, 0.20, 0.45):
                for mode in (0, 1, 2):
                    sample = unit * scale
                    sample[:, 6:] = abs(sample[:, 6:]) * 0.12
                    if mode != 1:
                        sample[:, 6:] = 0
                    if mode == 1:
                        sample[::2, 2] = 0
                    if mode == 2:
                        sample[:, 2] = 0
                        sample[:, 3] = (
                            sample[:, 0] + sample[:, 1] + unit[:, 3] * scale * 0.22
                        )
                    pts = coordinates(current, sample)
                    proposed += len(pts)
                    pts, metrics = filter_geometry(p, row, mask, cfg, pts, costs)
                    legal_count += len(pts)
                    if len(pts):
                        ix = rng.choice(len(pts), min(180, len(pts)), replace=False)
                        parts.append((pts[ix], metrics[ix]))
            xy = np.concatenate([z[0] for z in parts])
            metrics = np.concatenate([z[1] for z in parts])
            _, ix = np.unique(xy.reshape(len(xy), -1), axis=0, return_index=True)
            xy, metrics = xy[ix], metrics[ix]
            coarse = solve_set(pool, xy, metrics, 64)
            all_xy.extend(xy)
            all_metrics.extend(metrics)
            all_fields.extend(coarse)
            current = xy[np.argmin([c["peak_c"] for c in coarse])]
            summaries.append(
                dict(
                    proposals=proposed,
                    pass_geometry=legal_count,
                    coarse=len(coarse),
                    best_coarse_c=min(c["peak_c"] for c in coarse),
                )
            )
            print("round", step, summaries[-1], flush=True)
            if summaries[-1]["best_coarse_c"] < 108.90:
                break
        xy = np.asarray(all_xy)
        metrics = np.asarray(all_metrics)
        order = np.argsort([c["peak_c"] for c in all_fields])
        # A rigid translation changes the distance to the finite package boundary and the conformal grid.
        # Check actual translated geometries independently before ranking the final multi-grid witnesses.
        translated = []
        for i in order[:24]:
            for dy in np.arange(-1.5, 1.501, 0.075):
                translated.append(xy[i] + [0, dy])
        trxy, trmet = filter_geometry(
            p, row, mask, cfg, np.rint(np.array(translated) * 1000) / 1000, costs
        )
        trfields = solve_set(pool, trxy, trmet, 64)
        xy = np.concatenate([xy, trxy])
        metrics = np.concatenate([metrics, trmet])
        all_fields.extend(trfields)
        order = np.argsort([c["peak_c"] for c in all_fields])
        leading = list(order[:52])
        # Distinct poses avoid duplicating a single grid-alignment event.
        diversity = []
        for i in order:
            if all(np.linalg.norm(xy[i, :2] - xy[j, :2]) > 0.10 for j in diversity):
                diversity.append(i)
            if len(diversity) == 24:
                break
        ids = np.unique([*leading, *diversity])
        checks = {i: {64: all_fields[i]} for i in ids}
        for g in (96, 128):
            for i, c in zip(ids, solve_set(pool, xy[ids], metrics[ids], g)):
                checks[i][g] = c
        ranked = sorted(ids, key=lambda i: max(c["peak_c"] for c in checks[i].values()))
        winners = ranked[:4]
        for g in (160, 192):
            for i, c in zip(winners, solve_set(pool, xy[winners], metrics[winners], g)):
                checks[i][g] = c
        winner = min(
            winners, key=lambda i: max(c["peak_c"] for c in checks[i].values())
        )
        full = dict(
            row, id="two-fast-local", centres_um=np.rint(xy[winner] * 1000).tolist()
        )
        full["span_mm"] = float(np.ptp(xy[winner, :4], axis=0).sum())
        sz = sizes_mm(p, row["parity"])
        full["clearance_mm"] = float(
            np.maximum(
                abs(xy[winner, :4] - xy[winner, 4:]) - (sz[:4] + sz[4:]) / 2, 0
            ).sum()
        )
        full["joint_span_mm"] = full["span_mm"] + 2 * full["clearance_mm"]
        full.pop("score", None)
        full["necessary_fast"] = max(
            0, int(np.ceil((full["joint_span_mm"] - 47.314957544346605 - 1e-8) / 6.25))
        )
        w, mem, reach = metrics[winner]
        choice = dict(
            cfg,
            wire_m=w,
            memory_m=mem,
            max_cpu_signal_mm=reach,
            latency_ns=4.125 + reach / 150,
        )
        bundle = pin_check(p, full, mask, choice)
        # Translate all eight dies together; wires, port assignment and die spacings are identical.
        nearby = []
        for dy in (-0.1, -0.05, -0.025, 0.025, 0.05, 0.1):
            pt = xy[winner] + [0, dy]
            if not is_legal(
                p, Layout(np.rint(pt * 1000), np.array(choice["rotation_deg"])), 0
            ):
                continue
            fields = {
                g: solve_set(pool, [pt], [metrics[winner]], g)[0] for g in (64, 96, 128)
            }
            nearby.append(dict(translation_y_mm=dy, checks=fields))
    best_by_mask = []
    for m, c in enumerate(configurations(p, full, costs)):
        independent = exhaustive_wire(p, full, m)
        if c is None:
            assert np.isinf(independent)
        else:
            assert abs(c["wire_m"] - independent) < 1e-8
        best_by_mask.append(c["wire_m"] if c else None)
    out = dict(
        driver_sha256=digest(Path(__file__)),
        physics_sha256=digest(Path(__file__).with_name("mixed_phy.py")),
        refinement_sha256=digest(source),
        seed=seed["row"]["id"],
        mask=mask,
        rounds=summaries,
        translation_coarse=len(trxy),
        extra_grid_node_limit=450000,
        fine=len(ids),
        extra_grids=len(winners),
        witness=dict(
            layout=full, config=choice, checks=checks[winner], pin_bundles=bundle
        ),
        wires_by_mask=best_by_mask,
        nearby=nearby,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print(
        "five-grid peak", max(c["peak_c"] for c in checks[winner].values()), flush=True
    )


if __name__ == "__main__":
    main()
