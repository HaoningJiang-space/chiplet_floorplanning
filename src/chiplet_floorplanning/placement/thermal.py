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
WATER_CP_J_KGK = 4186.0
COLD_PLATE_BASE_MM = 3.0
FLOW_DIRECTIONS = ('+x', '-x', '+y', '-y')
PROVENANCE = ("ATPlace source geometry/power/pins; declared TAP-family FV materials, "
              "fixed 100/200 mm spreader/sink; not native ATPlace or measured calibration")


def _mixture(diameter, pitch, background):
    return 400*(diameter/pitch)**2 + background*(1 - (diameter/pitch)**2)


def thermal_case_data(problem, layout, gap_um, resolution=64, cold_plate_h_w_m2k=None):
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
    top_h = 1/(.1*.06**2)
    if cold_plate_h_w_m2k is not None:
        # Liquid cold plate (copper base on the lid) instead of the air sink; coolant enters at AMBIENT_C,
        # and h is the effective fin-side coefficient referred to the base area.
        layers = layers[:-1] + [layer("cold_plate", COLD_PLATE_BASE_MM, 400, 100, 100)]
        top_h = cold_plate_h_w_m2k
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


def solve_cold_plate(data, flow_kg_s, direction):
    """Steady solve with the top boundary at the local coolant temperature, which rises along `direction`
    ('+x', '-x', '+y' or '-y'). Coolant line k (one mesh line across the flow) holds c_k, defined at its
    centre: C (c_k - c_{k-1}) = (Q_{k-1} + Q_k)/2 and C c_0 = Q_0/2, with Q_k the heat the line picks up
    and C = flow * cp. Conduction and coolant are solved together as one sparse linear system.
    Returns (summary, power-layer rise field over coolant inlet, cell edges) like solve()."""
    from scipy.sparse import coo_matrix, bmat
    from scipy.sparse.linalg import splu
    case = parse_case(data)
    power, _ = rasterize(case)
    a, b, g, _, ids, power_z = assemble_package(case, power)
    require_heat_path(a, g)
    top = ids[-1]
    rows, cols = np.nonzero(top >= 0)
    node = top[rows, cols]
    line = (cols if direction[1] == 'x' else rows)
    order = np.unique(line)[::-1 if direction[0] == '-' else 1]
    position = np.empty(line.max() + 1, int)
    position[order] = np.arange(len(order))
    line, k, n = position[line], len(order), len(b)
    capacity = flow_kg_s*WATER_CP_J_KGK
    gn = g[node]
    line_g = np.bincount(line, gn, k)
    # conduction rows: A theta - sum_n g_n c_line(n) e_n = b
    couple = coo_matrix((-gn, (node, line)), shape=(n, k))
    # Q_k = sum_{n in k} g_n theta_n - G_k c_k ; coolant row k: C(c_k - c_{k-1}) - (Q_{k-1} + Q_k)/2 = 0
    pick = coo_matrix((gn, (line, node)), shape=(k, n)).tocsr()
    shift = coo_matrix((np.ones(k - 1), (np.arange(1, k), np.arange(k - 1))), shape=(k, k)).tocsr()
    eye = coo_matrix((np.ones(k), (np.arange(k), np.arange(k))), shape=(k, k)).tocsr()
    q_theta = pick + shift @ pick
    q_c = -(eye.multiply(line_g[None, :]) + shift.multiply(line_g[None, :]))
    coolant_c = capacity*(eye - shift) - .5*q_c
    system = bmat([[a, couple], [-.5*q_theta, coolant_c]]).tocsc()
    x = splu(system).solve(np.r_[b, np.zeros(k)])
    theta, c = x[:n], x[n:]
    residual = float(np.max(np.abs(system @ x - np.r_[b, np.zeros(k)])))
    removed = float(gn @ (theta[node] - c[line]))
    if residual > 1e-8 or abs(removed - b.sum()) > max(1e-10, 1e-8*b.sum()):
        raise ValueError("cold plate failed residual or energy check")
    layer = ids[power_z]
    field = np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan)
    summary = dict(peak_power_layer_c=float(np.nanmax(field) + case.thermal["ambient_c"]),
                   outlet_rise_k=float(b.sum()/capacity), heat_removed_w=removed, source_power_w=float(b.sum()),
                   physical_calibrated=False)
    edges = (np.concatenate(([0], np.cumsum(case.mesh.widths_mm))),
             np.concatenate(([0], np.cumsum(case.mesh.heights_mm))))
    return summary, field, edges


def die_peaks_c(problem, layout, rise, edges):
    """Hottest power-layer cell inside each die, degC (cell centres strictly inside the die box)."""
    width, height = (s/1000 for s in problem.carrier_um)
    offset = np.array([(PACKAGE_MM - width)/2, (PACKAGE_MM - height)/2])
    b = boxes(problem, layout)/1000 + np.r_[offset, offset]
    xc, yc = (edges[0][:-1] + edges[0][1:])/2, (edges[1][:-1] + edges[1][1:])/2
    peaks = []
    for x0, y0, x1, y1 in b:
        inside = np.ix_((yc > y0) & (yc < y1), (xc > x0) & (xc < x1))
        peaks.append(float(np.nanmax(rise[inside]) + AMBIENT_C))
    return np.array(peaks)
