"""Construct a full-netlist placement near the graph-cut upper bound on CPU centre span."""

import argparse
from itertools import product
from pathlib import Path
import json

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize

from case3_phy_experiment import EVIDENCE, inputs
from case3_phy_geometry import CAP_M, PROFILES, BundleLengths, direct_check
from case3_phy_thermal import solve_field
from chiplet_floorplanning.placement import Layout, is_legal
from compare_wire_heat import digest
from wide_floorplan import config_at, STATE
from wide_floorplan_moves import Assignment, SIGNS

TURNS = np.array([0, 90, 270, 180, 180, 270, 90, 0])
SIDES = [[3, 1], [2, 0], [2, 0], [3, 1]]
PARITY = [0, 1, 1, 0]


def centres(z):
    d, t, shift = z
    group = np.array([[-d, -t], [-d + 8.5, -t + shift]])
    quadrants = [group]
    for _ in range(3):
        v = quadrants[-1]
        quadrants.append(np.stack((-v[:, 1], v[:, 0]), axis=1))
    ordered = np.array(quadrants)[[0, 1, 3, 2]]
    return 19.5 + np.vstack((ordered[:, 0], ordered[:, 1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "first", "output"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--workers", type=int, default=1, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output")
    p, _, _ = inputs(args.data)
    costs = BundleLengths(p)
    STATE["costs"] = costs
    template = dict(
        parity=PARITY, profiles={"wide": dict(sides=SIDES, rotation_deg=TURNS.tolist())}
    )
    fixed = Assignment(p, template, costs)
    origin = centres(np.zeros(3)).ravel()
    jac = np.column_stack([centres(v).ravel() - origin for v in np.eye(3)])

    def cost(z):
        c, g = fixed.wire(origin + jac @ z)
        return c, g @ jac

    carrier = LinearConstraint(
        jac, (fixed.size / 2).ravel() - origin, (39 - fixed.size / 2).ravel() - origin
    )
    w = dict(
        type="ineq", fun=lambda z: CAP_M - 1e-8 - cost(z)[0], jac=lambda z: -cost(z)[1]
    )
    starts = 0
    results = []
    for z0 in product((10.5, 11.8), (-7.0, -5.5, 5.5, 7.0), (-0.334, 0.0, 0.334)):
        starts += 1
        rel = fixed.constraints(centres(z0), 0)
        a = rel.A @ jac
        b = rel.lb - rel.A @ origin
        b[:28] -= 0.0001  # The registered CPU/DRAM pairs touch.
        keep = np.abs(a).sum(axis=1) > 1e-12
        if max(b[~keep], default=0.0) > 1e-9:
            continue
        linear = LinearConstraint(a[keep], b[keep], np.inf)
        r = minimize(
            lambda z: -z[0],
            z0,
            jac=lambda z: np.array([-1.0, 0.0, 0.0]),
            constraints=[linear, carrier, w],
            bounds=Bounds([5, -10, -4], [15, 10, 4]),
            method="SLSQP",
            options=dict(maxiter=110, ftol=1e-11),
        )
        # A certified lower bound only uses the explicit legal witness on the native micron grid.
        for off in product(range(-2, 3), repeat=3):
            z = (np.rint(r.x * 1000) + np.array(off)) / 1000
            xy = np.rint(centres(z) * 1000)
            if not is_legal(p, Layout(xy, TURNS), 0):
                continue
            linear_xy = xy.ravel() / 1000
            c = fixed.wire(linear_xy)[0]
            if c > CAP_M or any(
                np.max(s - SIGNS @ ((xy[b] - xy[a]) / 1000)) > 25 + 1e-10
                for a, b, s in fixed.reach
            ):
                continue
            results.append(
                (float(np.ptp(xy[:4], axis=0).sum() / 1000), -float(c), tuple(z), xy)
            )
    assert results
    span, _, z, xy = max(results, key=lambda a: (a[0], a[1]))
    row = dict(template, id="span", centres_um=xy.tolist())
    choice = config_at(p, xy / 1000, row)
    row["profiles"] = {"wide": choice}
    direct_check(p, xy, choice, PROFILES["wide"])
    checks = {}
    for g in (64, 96, 128):
        field, _, err = solve_field(p, row, "wide", g, 1.0)
        checks[g] = dict(full_peak_c=float(np.nanmax(field)), energy_error_w=abs(err))
    floor = (
        json.loads((EVIDENCE / "case3-ring-certificate-v1.json").read_text())[
            "heat_lower_bound"
        ]["reserved_dram_bundle_sum_mm"]
        / 1000
    )
    upper = (CAP_M - floor) * 1000 / 704 + 15.6
    assert span <= upper + 1e-9
    out = dict(
        driver_sha256=digest(Path(__file__)),
        starts=starts,
        legal_trials=len(results),
        span_mm=span,
        universal_upper_mm=upper,
        remaining_gap_mm=upper - span,
        params_d_t_shift_mm=z,
        layout=row,
        checks=checks,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print(span, upper, choice["wire_m"], flush=True)


if __name__ == "__main__":
    main()
