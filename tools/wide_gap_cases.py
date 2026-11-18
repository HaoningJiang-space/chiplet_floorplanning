"""Check the clearance-cost identity on every archived original Case1--10 layout."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
from case3_phy_experiment import EVIDENCE
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import pin_points_um
from compare_wire_heat import digest
from wire_heat_bound import bundle_data


def run(job):
    data, prior = job
    name = prior["case"]
    src = data / "physical-calibration/atplace-import-v1" / f"{name}.json"
    run = data / "rs-grb-v4" / name.lower()
    assert (
        digest(src) == prior["case_sha256"]
        and digest(run / "summary.json") == prior["archive_sha256"]
    )
    p = Problem.from_imported(json.loads(src.read_text()))
    assert np.all(abs(p.pin_offset_um) <= p.size_um[p.pin_chip] / 2 + 1e-7)
    bundles, internal = bundle_data(p, 0)
    floor_m = (internal + sum(e["n"] * e["min_mm"] for e in bundles)) / 1000
    a, b = p.pin_chip.T
    slacks = []
    ratios = []
    neterror = 0
    shortest = None
    archive = run / "layouts.npz"
    with np.load(archive) as z:
        for i, (xy, rot, actual) in enumerate(
            zip(z["centre_um"], z["rotation_deg"], z["length_m"])
        ):
            layout = Layout(xy, rot)
            assert is_legal(p, layout, 0)
            size = np.where((rot % 180 != 0)[:, None], p.size_um[:, ::-1], p.size_um)
            centre = xy[b] - xy[a]
            gap = np.maximum(abs(centre) - (size[a] + size[b]) / 2, 0)
            shrink = np.sign(centre) * gap
            # Each pin pair keeps its two offsets; the contraction is per bundle, independently.
            d = np.diff(pin_points_um(p, layout), axis=1)[:, 0]
            residual = (
                abs(d).sum(axis=1) - abs(d - shrink).sum(axis=1) - gap.sum(axis=1)
            )
            neterror = max(neterror, float(np.max(abs(residual))))
            assert (
                np.max(abs(residual)) < 1e-6 and abs(abs(d).sum() / 1e6 - actual) < 1e-7
            )
            lower = floor_m + gap.sum() / 1e6
            slack = float(actual - lower)
            assert slack >= -1e-7
            slacks.append(slack)
            ratios.append((floor_m / actual, lower / actual))
            if shortest is None or actual < shortest["actual_wire_m"]:
                shortest = dict(
                    index=i,
                    actual_wire_m=float(actual),
                    floor_with_clearance_m=float(lower),
                )
    return dict(
        case=name,
        case_sha256=digest(src),
        layout_archive_sha256=digest(archive),
        dies=p.count,
        nets=len(a),
        bundles=len(bundles),
        layouts=len(ratios),
        zero_clearance_floor_m=floor_m,
        median_floor_fraction_without_clearance=float(
            np.median(np.array(ratios)[:, 0])
        ),
        median_floor_fraction_with_clearance=float(np.median(np.array(ratios)[:, 1])),
        min_slack_m=min(slacks),
        max_per_net_contraction_error_um=neterror,
        shortest=shortest,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output")
    record = EVIDENCE / "wire-heat-bound-v1.json"
    cases = [
        r
        for r in json.loads(record.read_text())["records"]
        if r["case"].startswith("Case")
    ]
    assert len(cases) == 10
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run, [(args.data, r) for r in cases]))
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                prior_sha256=digest(record),
                cases=rows,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    print("cases", len(rows), "layouts", sum(r["layouts"] for r in rows), flush=True)


if __name__ == "__main__":
    main()
