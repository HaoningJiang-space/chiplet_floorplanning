"""Separate DRAM heat and cooling requirements on fixed matched-span wide-interface layouts."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from case3_phy_experiment import EVIDENCE, inputs
from case3_phy_geometry import CAP_M, PROFILES, direct_check
from case3_phy_thermal import thermal_input
from chiplet_floorplanning.placement import solve
from compare_wire_heat import digest

STATE = {}


def setup(p):
    STATE["p"] = p


def field(row, grid, dram_w, h):
    powers = STATE["p"].power_w.copy()
    powers = powers.astype(float)
    powers[4:] = dram_w
    p = replace(STATE["p"], power_w=powers)
    data = thermal_input(p, row, "wide", grid, 1.0)
    data["thermal"]["top_h_w_m2k"] = h
    obs, rise, edges = solve(data)
    assert abs(obs["source_power_w"] - (608.192 + 4 * dram_w)) < 1e-7
    assert abs(obs["heat_removed_w"] - obs["source_power_w"]) < 1e-7
    return 45 + rise, obs, edges


def base(job):
    r, g, h = job
    a, _, edges = field(r, g, 0, h)
    b, obs, edges2 = field(r, g, 20, h)
    assert all(np.array_equal(x, y) for x, y in zip(edges, edges2))
    m = np.isfinite(a)
    assert np.array_equal(m, np.isfinite(b))
    slope = (b[m] - a[m]) / 20
    assert slope.min() >= -1e-8
    mask = slope > 1e-10
    w = None if np.max(a[m]) > 109 else float(np.min((109 - a[m][mask]) / slope[mask]))
    assert abs(np.nanmax(b) - r["checks"][str(g)]["peak_c"]) < 1e-6
    return g, dict(
        zero_memory_peak_c=float(np.nanmax(a)),
        nominal_peak_c=float(np.nanmax(b)),
        max_memory_w_each=w,
        energy_balance_w=abs(obs["energy_balance_error_w"]),
    )


def test(job):
    r, g, w, h = job
    t, obs, _ = field(r, g, w, h)
    return g, dict(
        peak_c=float(np.nanmax(t)), energy_balance_w=abs(obs["energy_balance_error_w"])
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output path")
    p, _, _ = inputs(args.data)
    files = [args.output.parent / name for name in ("layout.json", "square.json")]
    rows = [
        r
        for f in files
        for r in json.loads(f.read_text())["rows"]
        if set(r["checks"]) == {"64", "96", "128"}
    ]
    cap = json.loads((EVIDENCE / "case3-interface-cut-v1.json").read_text())[
        "wide_span"
    ]["universal_upper_mm"]
    relaxed = min(
        (r for r in rows if r["span_mm"] <= cap),
        key=lambda r: max(v["peak_c"] for v in r["checks"].values()),
    )
    tight = min(
        (r for r in rows if r["profiles"]["wide"]["wire_m"] <= CAP_M),
        key=lambda r: max(v["peak_c"] for v in r["checks"].values()),
    )
    span = next(r for r in rows if r["id"] == "prior-span")
    cold = min(rows, key=lambda r: max(v["peak_c"] for v in r["checks"].values()))
    chosen = {
        "primary": tight,
        "maximum_span": span,
        "span_only": relaxed,
        "larger_span": cold,
    }
    nominal_h = float(p.top_h_w_m2k or 1 / (0.1 * 0.06**2))
    grids = (64, 96, 128)
    out = {}
    with ProcessPoolExecutor(args.workers, initializer=setup, initargs=(p,)) as pool:
        for tag, r in chosen.items():
            direct_check(
                p, np.array(r["centres_um"]), r["profiles"]["wide"], PROFILES["wide"]
            )
            checks = dict(pool.map(base, [(r, g, nominal_h) for g in grids]))
            limits = [x["max_memory_w_each"] for x in checks.values()]
            w = min(limits) if all(x is not None for x in limits) else None
            direct = None
            if w is not None:
                direct = dict(pool.map(test, [(r, g, w, nominal_h) for g in grids]))
                assert abs(max(x["peak_c"] for x in direct.values()) - 109) < 1e-6

            # A one-sided increase in positive top shunts reduces every temperature.
            def cool(h):
                measurements = dict(pool.map(test, [(r, g, 20, h) for g in grids]))
                return max(x["peak_c"] for x in measurements.values()), measurements

            lo = nominal_h
            hi = lo
            results = {
                lo: {g: {"peak_c": x["nominal_peak_c"]} for g, x in checks.items()}
            }
            if max(x["nominal_peak_c"] for x in checks.values()) > 109:
                while True:
                    hi *= 1.35
                    peak, results[hi] = cool(hi)
                    if peak <= 109:
                        break
                    if hi > 1e6:
                        raise RuntimeError(
                            "cooling target unreachable over search interval"
                        )
                while hi - lo > 2:
                    mid = (hi + lo) / 2
                    peak, results[mid] = cool(mid)
                    if peak <= 109:
                        hi = mid
                    else:
                        lo = mid
            out[tag] = dict(
                layout=r,
                nominal_h_w_m2k=nominal_h,
                checks=checks,
                memory_limit_w_each=w,
                direct_at_limit=direct,
                cooling_bracket_w_m2k=[lo, hi] if lo != hi else None,
                feasible_cooling_w_m2k=hi,
                checks_at_bracket={str(h): results[h] for h in (lo, hi)},
                cooling_steps=len(results),
            )
    args.output.write_text(
        json.dumps(
            dict(
                driver_sha256=digest(Path(__file__)),
                inputs={p.name: digest(p) for p in files},
                points=out,
            ),
            allow_nan=False,
        )
        + "\n"
    )
    print(
        [
            (k, v["memory_limit_w_each"], v["cooling_bracket_w_m2k"])
            for k, v in out.items()
        ],
        flush=True,
    )


if __name__ == "__main__":
    main()
