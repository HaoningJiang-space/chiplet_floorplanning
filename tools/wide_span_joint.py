"""Check the additive CPU span and matched-memory clearance inequality on actual pins."""

import argparse
from itertools import permutations, product
import json
from pathlib import Path

import numpy as np
from case3_phy_experiment import EVIDENCE, inputs, STATE
from case3_phy_geometry import BundleLengths, CAP_M, PROFILES, direct_check
from chiplet_floorplanning.placement import Layout, is_legal
from chiplet_floorplanning.placement.geometry import rotate
from compare_wire_heat import digest
from wide_floorplan import config_at
from wide_floorplan_moves import Assignment, SIGNS
from wide_span_layouts import rotate4


def pin_offsets(p):
    out = {}
    for i in range(4):
        keep = (p.pin_chip == i).any(axis=1) & (p.pin_chip == i + 4).any(axis=1)
        off = p.pin_offset_um[keep].copy() / 1000
        reverse = p.pin_chip[keep, 0] != i
        off[reverse] = off[reverse, ::-1]
        assert len(off) == 1408
        for a, b in product(range(4), repeat=2):
            out[i, a, b] = rotate(off[:, 1], 90 * b) - rotate(off[:, 0], 90 * a)
    return out


def check(r, offsets, reserve):
    xy = np.array(r["centres_um"]) / 1000
    cfg = r["profiles"]["wide"]
    turns = np.array(cfg["rotation_deg"]) // 90
    sizes = np.array([[9, 8] if v % 2 else [8, 9] for v in turns[:4]])
    half = (sizes + 9) / 2
    delta = xy[4:] - xy[:4]
    axes = np.maximum(abs(delta) - half, 0)
    closed = delta - np.sign(delta) * axes
    assert np.min(np.max(abs(closed) - half, axis=1)) >= -1e-9
    sums = (
        np.array(
            [
                [
                    np.abs(displacement + offsets[i, turns[i], turns[i + 4]]).sum()
                    for i, displacement in enumerate(array)
                ]
                for array in (delta, closed)
            ]
        )
        / 1000
    )
    error = float(np.max(abs(sums[0] - sums[1] - 1.408 * axes.sum(axis=1))))
    assert error < 1e-9 and abs(sums[0].sum() - cfg["memory_m"]) < 1e-8
    assert sums[1].sum() >= reserve - 1e-8
    g = float(axes.sum())
    span = float(np.ptp(xy[:4], axis=0).sum())
    all_g = np.maximum(abs(xy[:4, None] - xy[None, 4:]) - half[:, None], 0).sum(axis=2)
    best = min(all_g[range(4), list(perm)].sum() for perm in permutations(range(4)))
    lower = reserve + 1.408 * g + 0.352 * max(0, 2 * span - 31.2)
    assert cfg["wire_m"] >= lower - 1e-8
    return dict(
        span_mm=span,
        matched_clearance_sum_mm=g,
        best_relabelled_clearance_sum_mm=float(best),
        joint_span_mm=span + 2 * g,
        actual_wire_m=cfg["wire_m"],
        joint_wire_floor_m=lower,
        wire_slack_m=cfg["wire_m"] - lower,
        contraction_error_m=error,
    )


def constructions(p, upper):
    # Move the four memories identically away from their CPUs, maintaining the registered ring turns.
    turns = [0, 90, 270, 180, 180, 270, 90, 0]
    row = dict(
        parity=[0, 1, 1, 0],
        profiles={
            "wide": dict(rotation_deg=turns, sides=[[3, 1], [2, 0], [2, 0], [3, 1]])
        },
    )
    fixed = Assignment(p, row, STATE["costs"])
    out = []
    for g in (0, 0.025, 0.05, 0.1, 0.25, 0.5, 1):
        best = None
        top = np.floor((upper - 8 * g) * 250) / 1000
        for delta in np.r_[
            np.arange(0, 0.1, 0.001),
            np.arange(0.1, 1.01, 0.01),
            np.arange(1.1, 4.01, 0.1),
        ]:
            d = round(top - delta, 3)
            # Keep adjacent memories tangent in the central region; the leftover sweep allows sliding.
            for margin in (0.0, 0.01, 0.05, 0.15, 0.3, 0.6, 1.0):
                t = d - 17.5 - g - margin
                cpu = rotate4(np.array([[-d, -t]]))[0]
                ram = rotate4(np.array([[-d + 8.5 + g, -t]]))[0]
                xy = np.rint((19.5 + np.vstack([cpu, ram])) * 1000)
                if not is_legal(p, Layout(xy, np.array(turns)), 0):
                    continue
                if fixed.wire(xy.ravel() / 1000)[0] > CAP_M:
                    continue
                if any(
                    np.max(s - SIGNS @ ((xy[b] - xy[a]) / 1000)) > 25 + 1e-10
                    for a, b, s in fixed.reach
                ):
                    continue
                cfg = config_at(p, xy / 1000, row)
                direct_check(p, xy, cfg, PROFILES["wide"])
                best = dict(
                    row, id=f"gap-{g}", centres_um=xy.tolist(), profiles={"wide": cfg}
                )
                break
            if best:
                break
        out.append(dict(gap_mm_each=g, layout=best))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use fresh output")
    p, _, _ = inputs(args.data)
    STATE["costs"] = BundleLengths(p)
    source = EVIDENCE / "case3-interface-cut-v1.json"
    past = json.loads(source.read_text())
    floor = past["memory_floor_m"]
    upper = past["wide_span"]["universal_upper_mm"]
    files = [
        args.output.parent / "layout.json",
        args.output.parent / "square.json",
        args.data / "wide-continuous-f23b0a0-um/heat.json",
    ]
    assert digest(files[-1]) == past["raw_sha256"]["heat.json"]
    offsets = pin_offsets(p)
    frozen = constructions(p, upper)
    for item in frozen:
        if row := item["layout"]:
            item["metrics"] = check(row, offsets, floor)
    stats = []
    points = {}
    for f in files:
        rows = json.loads(f.read_text())["rows"]
        metrics = [check(r, offsets, floor) for r in rows]
        stats.append(
            dict(
                name=f.name,
                rows=len(rows),
                max_contraction_error_m=max(c["contraction_error_m"] for c in metrics),
                min_wire_slack_m=min(c["wire_slack_m"] for c in metrics),
            )
        )
        for r, v in zip(rows, metrics):
            if set(r["checks"]) != {"64", "96", "128"}:
                continue
            peak = max(k["peak_c"] for k in r["checks"].values())
            groups = {}
            if v["span_mm"] <= upper + 1e-8:
                groups["span_only"] = peak
            if v["actual_wire_m"] <= CAP_M:
                groups["primary"] = peak
            if peak <= 109:
                groups["cold_smallest_joint"] = v["joint_span_mm"]
                groups["cold_smallest_wire"] = v["actual_wire_m"]
            if r["id"] == "prior-span":
                groups["maximum_span"] = peak
            for key, value in groups.items():
                if key not in points or points[key]["selection_value"] > value:
                    points[key] = dict(
                        id=r["id"],
                        selection_value=value,
                        full_peak_c=peak,
                        metrics=v,
                        layout=r,
                    )
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                source_sha256=digest(source),
                raw_sha256={f.name: digest(f) for f in files},
                populations=stats,
                constructions=frozen,
                points=points,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    print(
        [(r["gap_mm_each"], r.get("metrics", {}).get("joint_span_mm")) for r in frozen],
        flush=True,
    )


if __name__ == "__main__":
    main()
