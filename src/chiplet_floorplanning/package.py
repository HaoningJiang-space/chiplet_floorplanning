"""Multilayer finite-volume conduction with explicit die islands and voids."""

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


def assemble_package(case, power):
    cfg = case.thermal
    layers = cfg["layers"]
    dx_mm, dy_mm = case.package.width / case.nx, case.package.height / case.ny
    dx, dy = dx_mm * 1e-3, dy_mm * 1e-3
    die_mask = np.zeros((case.ny, case.nx), dtype=bool)
    for die in case.dies:
        r = die.bounds
        edges = [r.x / dx_mm, (r.x + r.width) / dx_mm, r.y / dy_mm, (r.y + r.height) / dy_mm]
        if not np.allclose(edges, np.round(edges), rtol=0, atol=1e-8):
            raise ValueError("layered package requires chiplet boundaries aligned to thermal grid")
        x0, x1, y0, y1 = map(lambda x: int(round(x)), edges)
        die_mask[y0:y1, x0:x1] = True
    ids = np.full((len(layers), case.ny, case.nx), -1, dtype=int)
    nodes = []
    for z, layer in enumerate(layers):
        mask = die_mask if layer["footprint"] == "chiplets" else np.ones_like(die_mask)
        for y, x in zip(*np.where(mask)):
            ids[z, y, x] = len(nodes)
            nodes.append((z, int(y), int(x)))
    diagonal = np.zeros(len(nodes))
    sink = np.zeros(len(nodes))
    rhs = np.zeros(len(nodes))
    rows, cols, values = [], [], []
    power_z = [layer["id"] for layer in layers].index(cfg["power_layer"])
    power = np.asarray(power, dtype=float)
    if power.shape != (case.ny, case.nx) or not np.all(np.isfinite(power)) or np.any(power < 0):
        raise ValueError("invalid power grid")
    if np.any(power[ids[power_z] < 0] != 0):
        raise ValueError("heat source outside active package material")
    for a, (z, y, x) in enumerate(nodes):
        k = layers[z]["conductivity_w_mk"]
        t = layers[z]["thickness_mm"] * 1e-3
        if z == power_z:
            rhs[a] = power[y, x]
        for zz, yy, xx, g in ((z, y, x + 1, k * t * dy / dx), (z, y + 1, x, k * t * dx / dy)):
            if yy < case.ny and xx < case.nx and ids[zz, yy, xx] >= 0:
                b = ids[zz, yy, xx]
                rows.extend((a, b)); cols.extend((b, a)); values.extend((-g, -g))
                diagonal[a] += g
                diagonal[b] += g
        if z + 1 < len(layers) and ids[z + 1, y, x] >= 0:
            other = layers[z + 1]
            g = dx * dy / (t / (2 * k) + other["thickness_mm"] * 1e-3 / (2 * other["conductivity_w_mk"]))
            b = ids[z + 1, y, x]
            rows.extend((a, b)); cols.extend((b, a)); values.extend((-g, -g))
            diagonal[a] += g
            diagonal[b] += g
        for boundary, h in ((0, cfg["bottom_h_w_m2k"]), (len(layers) - 1, cfg["top_h_w_m2k"])):
            if z == boundary and h > 0:
                sink[a] += dx * dy / (t / (2 * k) + 1 / h)
    rows.extend(range(len(nodes))); cols.extend(range(len(nodes))); values.extend(diagonal + sink)
    matrix = coo_matrix((values, (rows, cols)), shape=(len(nodes), len(nodes))).tocsr()
    return matrix, rhs, sink, nodes, ids, power_z


def solve_package(case, power):
    matrix, rhs, sink, nodes, ids, power_z = assemble_package(case, power)
    rise = spsolve(matrix, rhs)
    residual = float(np.max(np.abs(matrix @ rise - rhs)))
    removed = float(sink @ rise)
    if not np.all(np.isfinite(rise)) or residual > 1e-8 or abs(removed - rhs.sum()) > max(1e-10, 1e-8 * rhs.sum()):
        raise ValueError("package failed finite solution, residual or energy check")
    temperature = np.full((case.ny, case.nx), np.nan)
    source = ids[power_z] >= 0
    temperature[source] = rise[ids[power_z][source]] + case.thermal["ambient_c"]
    summary = {"model": case.thermal["model"], "calibration": "not_calibrated",
               "provenance": case.thermal["provenance"], "reported_layer": case.thermal["power_layer"],
               "peak_c": float(np.nanmax(temperature)), "minimum_c": float(np.nanmin(temperature)),
               "mean_c": float(np.nanmean(temperature)), "removed_heat_w": removed,
               "energy_balance_error_w": float(removed - rhs.sum()), "linear_residual_inf_w": residual,
               "node_count": len(nodes), "all_node_temperature_c": (rise + case.thermal["ambient_c"]).tolist(),
               "node_indices_layer_y_x": nodes}
    return temperature, summary
