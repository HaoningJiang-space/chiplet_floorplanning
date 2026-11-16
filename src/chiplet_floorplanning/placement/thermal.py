"""Declared TAP-family FV package for imported cases, solved with scipy.

This is the same material recipe as tools/atplace_pin_geometry.make_thermal_case:
fixed 100 mm spreader, 200 mm sink, top Robin h and adiabatic sides/bottom.
It is a research adaptation, not ATPlace's native model or a measured package.
Ports are omitted because they do not enter the mesh, materials or power map.
"""
from dataclasses import replace

import numpy as np

from ..model import parse_case
from ..package import assemble_package, checked_solution, require_heat_path, solve_spd
from ..power import rasterize
from .geometry import boxes, violations

AMBIENT_C = 45.0
PACKAGE_MM = 200.0
PROVENANCE = ("ATPlace source geometry/power/pins; declared TAP-family FV materials, "
              "fixed 100/200 mm spreader/sink; not native ATPlace or measured calibration")


def _mixture(diameter, pitch, background):
    return 400*(diameter/pitch)**2 + background*(1 - (diameter/pitch)**2)


def thermal_case_data(problem, layout, gap_um, resolution=64, top_h_w_m2k=None):
    """Declared TAP-family FV case; top_h_w_m2k overrides the sink-top convection (default 1/(0.1 K/W x 60 mm square))."""
    v = violations(problem, layout, gap_um)
    if v["outside"] or v["pairs"]:
        raise ValueError(f"illegal layout: {v}")
    width, height = (s/1000 for s in problem.carrier_um)
    if max(width, height) > 100:
        raise ValueError("source carrier exceeds this declared common spreader")
    ox, oy = (PACKAGE_MM - width)/2, (PACKAGE_MM - height)/2
    b = boxes(problem, layout)
    chips = []
    for k, name in enumerate(problem.names):
        w, h = problem.size_um[k]/1000
        chips.append(dict(id=name, size_mm=dict(width=w, height=h),
                          placement_mm=dict(x=ox + b[k, 0]/1000, y=oy + b[k, 1]/1000),
                          rotation_deg=int(layout.rotation_deg[k]), ports_mm={},
                          blocks=[dict(id="core", rect_mm=dict(x=0, y=0, width=w, height=h),
                                       power_w=float(problem.power_w[k]), provenance=PROVENANCE)]))

    def layer(name, thickness, conductivity, w=width, h=height, die_k=None):
        item = dict(id=name, thickness_mm=thickness, conductivity_w_mk=conductivity,
                    footprint="rectangle", rect_mm=dict(x=(200 - w)/2, y=(200 - h)/2, width=w, height=h))
        if die_k is not None:
            item["die_materials"] = {c["id"]: dict(conductivity_w_mk=die_k) for c in chips}
        return item

    layers = [layer("substrate", .2, 1/3.33), layer("c4", .07, _mixture(250, 600, 1.6)),
              layer("interposer", .11, _mixture(10, 50, 100)),
              layer("microbumps", .01, 1.6, die_k=_mixture(25, 45, 1.6)),
              layer("dies", .15, 1.6, die_k=100), layer("tim", .02, 4),
              layer("spreader", 1, 400, 100, 100), layer("sink", 6.9, 400, 200, 200)]
    top_h = top_h_w_m2k if top_h_w_m2k is not None else 1/(.1*.06**2)
    return dict(schema_version=1, name="atplace_fv_" + problem.name,
                package_mm=dict(width=200, height=200),
                grid=dict(nx=resolution, ny=resolution, mode="geometry_conformal"), chiplets=chips,
                thermal=dict(model="layered_package_steady", ambient_c=AMBIENT_C, top_h_w_m2k=top_h,
                             bottom_h_w_m2k=0, power_layer="dies", provenance=PROVENANCE, layers=layers),
                interconnect=dict(model="manhattan_lower_bound", r_ohm_per_mm=0, c_pf_per_mm=0,
                                  provenance="unused; source pins are evaluated separately"),
                links=[])


def solve(data):
    """Steady solve; power-layer peak (degC), energy-balance bookkeeping and the
    power-layer rise field (K) on mesh cells, with cell edges in package mm."""
    case = parse_case(data)
    power, _ = rasterize(case)
    a, b, g, _, ids, power_z = assemble_package(case, power)
    require_heat_path(a, g)
    theta = solve_spd(a, b)
    residual, removed = checked_solution(a, b, g, theta)
    layer = ids[power_z]
    rise = np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan)
    summary = dict(peak_power_layer_c=float(np.nanmax(rise) + case.thermal["ambient_c"]),
                   source_power_w=float(b.sum()), heat_removed_w=removed,
                   energy_balance_error_w=removed - float(b.sum()), linear_residual_inf_w=residual,
                   min_rise_k=float(theta.min()),
                   physical_calibrated=False)
    edges = (np.concatenate(([0], np.cumsum(case.mesh.widths_mm))),
             np.concatenate(([0], np.cumsum(case.mesh.heights_mm))))
    return summary, rise, edges


def solve_peak(data):
    return solve(data)[0]


def power_layer_responses(problem, layout, gap_um, powers, resolution=64):
    """Power-layer rise fields (K, NaN outside dies) for each row of `powers` (W per chiplet) on one layout,
    and the cell edges (package mm). The conduction matrix does not depend on power, so it is factorised
    once; fields superpose linearly."""
    from scipy.sparse.linalg import splu
    fields = []
    for k, p in enumerate(np.atleast_2d(powers)):
        case = parse_case(thermal_case_data(replace(problem, power_w=np.asarray(p, float)), layout, gap_um, resolution))
        power, _ = rasterize(case)
        a, b, g, _, ids, power_z = assemble_package(case, power)
        if k == 0:
            require_heat_path(a, g)
            lu = splu(a.tocsc(), permc_spec="MMD_AT_PLUS_A")
        theta = lu.solve(b)
        checked_solution(a, b, g, theta)
        layer = ids[power_z]
        fields.append(np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan))
    edges = (np.concatenate(([0], np.cumsum(case.mesh.widths_mm))),
             np.concatenate(([0], np.cumsum(case.mesh.heights_mm))))
    return np.array(fields), edges


def die_peak_sensitivity(problem, layout, gap_um, resolution=64):
    """Exact solve plus first-order die-peak sensitivities from one LU factorisation.

    Returns (die peaks degC (n,), gradient K/mm (n, n, 2)): grad[i, j] = d(peak of die i)/d(centre of die j).
    By reciprocity, one adjoint solve psi_i = A^-1 e_(hottest cell of die i) gives the rise at that cell per
    watt at every node; shifting die j's uniform source by dx changes it by q_j * dx * (integral of
    d psi_i/dx over die j). The mean slope comes from die j's first and last cell centres scaled to its full
    width, or, for a die only one cell wide, from the microbump-layer cells just outside it. The hottest cell
    moves with its own die, so the self term is minus the sum of the others (translation invariance). The
    conduction change of the moving die is neglected, so callers must confirm every step with an exact solve.
    """
    from scipy.sparse.linalg import splu
    case = parse_case(thermal_case_data(problem, layout, gap_um, resolution))
    power, _ = rasterize(case)
    a, b, g, _, ids, power_z = assemble_package(case, power)
    require_heat_path(a, g)
    lu = splu(a.tocsc(), permc_spec="MMD_AT_PLUS_A")
    theta = lu.solve(b)
    checked_solution(a, b, g, theta)
    layer = ids[power_z]
    field = np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan)
    edges = (np.concatenate(([0], np.cumsum(case.mesh.widths_mm))),
             np.concatenate(([0], np.cumsum(case.mesh.heights_mm))))
    centres = [(e[:-1] + e[1:])/2 for e in edges]   # mm: x, y cell centres
    cells = [(r.ravel(), c.ravel()) for r, c in die_cells(problem, layout, edges)]
    dy, dx = case.mesh.heights_mm, case.mesh.widths_mm
    n = problem.count
    q = problem.power_w/np.array([dy[r].sum()*dx[c].sum() for r, c in cells])  # W/mm^2
    below = ids[power_z - 1]

    def slopes(values, under, rows, cols, axis):
        """Mean d psi/d(axis) per strip across die (rows, cols), K/W per mm."""
        idx, strips, length = (cols, rows, dx[cols].sum()) if axis == 0 else (rows, cols, dy[rows].sum())
        c = centres[axis]
        if idx.size > 1:
            take = (lambda k: values[strips, k]) if axis == 0 else (lambda k: values[k, strips])
            return (take(idx[-1]) - take(idx[0]))/(c[idx[-1]] - c[idx[0]]), length
        take = (lambda k: under[strips, k]) if axis == 0 else (lambda k: under[k, strips])
        lo, hi = max(idx[0] - 1, 0), min(idx[0] + 1, len(c) - 1)
        lo = lo if np.isfinite(take(lo)).all() else idx[0]    # no layer outside the carrier: one-sided
        hi = hi if np.isfinite(take(hi)).all() else idx[0]
        return ((take(hi) - take(lo))/(c[hi] - c[lo]) if hi != lo else np.zeros(strips.size)), length

    peaks, grad = np.zeros(n), np.zeros((n, n, 2))
    for i, (rows, cols) in enumerate(cells):
        sub = field[np.ix_(rows, cols)]
        r, c = np.unravel_index(np.nanargmax(sub), sub.shape)
        peaks[i] = sub[r, c]
        unit = np.zeros(a.shape[0])
        unit[layer[rows[r], cols[c]]] = 1.0
        adjoint = lu.solve(unit)
        psi = np.where(layer >= 0, adjoint[np.maximum(layer, 0)], np.nan)
        under = np.where(below >= 0, adjoint[np.maximum(below, 0)], np.nan)
        for j, (rj, cj) in enumerate(cells):
            sx, wx = slopes(psi, under, rj, cj, 0)
            sy, wy = slopes(psi, under, rj, cj, 1)
            grad[i, j, 0] = q[j]*wx*(sx*dy[rj]).sum()
            grad[i, j, 1] = q[j]*wy*(sy*dx[cj]).sum()
        grad[i, i] = 0.0
        grad[i, i] = -grad[i].sum(axis=0)
    return peaks + case.thermal["ambient_c"], grad


def die_cells(problem, layout, edges):
    """Per die, the (row, col) index of the power-layer cells whose centres lie strictly inside the die box."""
    width, height = (s/1000 for s in problem.carrier_um)
    offset = np.array([(PACKAGE_MM - width)/2, (PACKAGE_MM - height)/2])
    b = boxes(problem, layout)/1000 + np.r_[offset, offset]
    xc, yc = (edges[0][:-1] + edges[0][1:])/2, (edges[1][:-1] + edges[1][1:])/2
    return [np.ix_((yc > y0) & (yc < y1), (xc > x0) & (xc < x1)) for x0, y0, x1, y1 in b]


def die_peaks_c(problem, layout, rise, edges):
    """Hottest power-layer cell inside each die, degC (cell centres strictly inside the die box)."""
    return np.array([float(np.nanmax(rise[inside]) + AMBIENT_C) for inside in die_cells(problem, layout, edges)])
