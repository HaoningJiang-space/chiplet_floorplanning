"""Verify the number of faster links at three common geometric targets with the full thermal model."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np

from case3_phy_experiment import EVIDENCE, STATE, inputs, setup_geometry
from case3_phy_geometry import CAP_M, BundleLengths, sizes_mm
from compare_wire_heat import digest
from mixed_link_audit import decision
from mixed_link_experiment import read
from mixed_phy import configurations, temperature, pin_check


def full_field(job):
    row, mask, cfg, grid = job
    return grid, temperature(
        STATE["p"], row, mask, cfg, grid, node_limit=450000 if grid >= 160 else 250000
    )


def four_link(p):
    prior = read(EVIDENCE / "case3-interface-cut-v1.json")
    point = read(STATE["cut_file"])["points"]
    original = next(r for r in point if r["id"] == "q-17-10-1--1")
    assert digest(STATE["cut_file"]) == prior["raw_sha256"]["cut.json"]
    cfg = original["config"]
    parity = (np.array(cfg["rotation_deg"])[:4] // 90 % 2).tolist()
    xy = np.array(original["centres_um"])
    size = sizes_mm(p, parity) * 1000
    delta = xy[4:] - xy[:4]
    gaps = abs(delta) - (size[:4] + size[4:]) / 2
    axis = gaps.argmax(axis=1)
    assert np.allclose(gaps[np.arange(4), axis], 1000)
    xy[4 + np.arange(4), axis] += 50 * np.sign(delta[np.arange(4), axis])
    row = dict(id="four-fast-50um", centres_um=xy.tolist(), parity=parity)
    chosen = configurations(p, row, BundleLengths(p))[15]
    assert abs(chosen["wire_m"] - cfg["wire_m"] - 0.2816) < 1e-8
    return row, 15, chosen


def nearby_clearances(p, pool, point):
    """Shrink the CPU ring in 10--150 micron increments, moving each matched memory with its CPU."""
    base = np.array(point["layout"]["centres_um"])
    mask = 9
    size = sizes_mm(p, point["layout"]["parity"])
    signs = np.sign(base[:4] - 19500)
    cases = []
    for sx, sy in [
        (10, 10),
        (25, 25),
        (50, 50),
        (100, 100),
        (150, 150),
        (25, 0),
        (0, 25),
        (50, 0),
        (0, 50),
    ]:
        vector = signs * np.array([sx, sy])
        xy = base - np.vstack((vector, vector))
        row = dict(
            id=f"two-fast-inset-{sx}-{sy}",
            centres_um=xy.tolist(),
            parity=point["layout"]["parity"],
        )
        cfg = configurations(p, row, STATE["costs"])[mask]
        span = float(np.ptp(xy[:4], axis=0).sum() / 1000)
        gap = float(
            np.maximum(abs(xy[:4] - xy[4:]) / 1000 - (size[:4] + size[4:]) / 2, 0).sum()
        )
        pin_check(p, row, mask, cfg)
        checks = dict(
            pool.map(full_field, [(row, mask, cfg, g) for g in (64, 96, 128, 160, 192)])
        )
        cases.append(
            dict(
                id=row["id"],
                centres_um=xy.tolist(),
                parity=row["parity"],
                mask=mask,
                inward_x_um=sx,
                inward_y_um=sy,
                span_mm=span,
                clearance_mm=gap,
                joint_span_mm=span + 2 * gap,
                actual_config=cfg,
                checks=checks,
                length_scale_limit=min(
                    CAP_M / cfg["wire_m"], 25 / cfg["max_cpu_signal_mm"]
                ),
            )
        )
    return cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "output"):
        ap.add_argument("--" + k, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use fresh output")
    p, _, _ = inputs(args.data)
    local_path = args.output.parent / "local.json"
    ref_path = args.output.parent / "refine.json"
    local = read(local_path)
    ref = read(ref_path)
    cert = next(
        x["certificate"]
        for x in read(EVIDENCE / "global-heat-floor-v1.json")["cases"]
        if x["certificate"]["case"] == "Case3"
    )
    setup_geometry(p, cert)
    STATE["cut_file"] = args.data / "wide-continuous-f23b0a0-um/cut.json"
    two = local["witness"]
    three = min(
        (
            v
            for v in ref["records"]
            if v["mask"].bit_count() == 3
            and v["row"]["span_mm"] >= 60
            and v["config"]["wire_m"] <= CAP_M
        ),
        key=lambda v: max(c["peak_c"] for c in v["checks"].values()),
    )
    targets = [
        (two["layout"], local["mask"], two["config"]),
        (three["row"], three["mask"], three["config"]),
        four_link(p),
    ]
    result = []
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        for row, mask, cfg in targets:
            xy = np.array(row["centres_um"]) / 1000
            size = sizes_mm(p, row["parity"])
            span = float(np.ptp(xy[:4], axis=0).sum())
            gap = float(
                np.maximum(abs(xy[4:] - xy[:4]) - (size[4:] + size[:4]) / 2, 0).sum()
            )
            z = span + 2 * gap
            lower = int(np.ceil((z - 47.314957544346605 - 1e-8) / 6.25))
            a = decision(row)
            min_w = [
                None if v is None else v["wire_m"] for v in a["all_parity_min_by_mask"]
            ]
            exact = min(
                m.bit_count()
                for m, w in enumerate(min_w)
                if w is not None and w <= CAP_M
            )
            assert exact == lower == mask.bit_count()
            pin = pin_check(p, row, mask, cfg)
            checks = dict(
                pool.map(
                    full_field, [(row, mask, cfg, g) for g in (64, 96, 128, 160, 192)]
                )
            )
            wire = min(
                (
                    w
                    for m, w in enumerate(min_w)
                    if w is not None and m.bit_count() < exact
                ),
                default=None,
            )
            result.append(
                dict(
                    id=row["id"],
                    centres_um=row["centres_um"],
                    parity=row["parity"],
                    span_mm=span,
                    clearance_mm=gap,
                    joint_span_mm=z,
                    minimum_fast_from_bound=lower,
                    minimum_fast_all_rotations=exact,
                    legal_footprints=a["legal_parities"],
                    brute_states=a["port_assignments"],
                    all_rotations_min_wire_by_mask=min_w,
                    cheapest_fewer_upgrades_wire_m=wire,
                    mask=mask,
                    actual_config=cfg,
                    pin_bundles=pin,
                    checks=checks,
                )
            )
        nearby = nearby_clearances(p, pool, two)
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                physics_sha256=digest(Path(__file__).with_name("mixed_phy.py")),
                inputs={
                    p.name: digest(p) for p in (local_path, ref_path, STATE["cut_file"])
                },
                points=result,
                neighboring_designs=nearby,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    for r in result:
        print(
            r["mask"],
            r["joint_span_mm"],
            r["actual_config"]["wire_m"],
            max(c["peak_c"] for c in r["checks"].values()),
            flush=True,
        )


if __name__ == "__main__":
    main()
