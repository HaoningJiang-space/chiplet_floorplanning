"""Multilayer finite-volume conduction with explicit die islands and voids."""

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from time import perf_counter


def conductivity_xyz(layer):
    return layer.get('conductivity_xyz_w_mk', [layer.get('conductivity_w_mk')]*3)


def rectangle_slice(case, rect):
    indices = []
    for axis, value in ((case.mesh.x_edges_mm, rect.x), (case.mesh.x_edges_mm, rect.x+rect.width),
                        (case.mesh.y_edges_mm, rect.y), (case.mesh.y_edges_mm, rect.y+rect.height)):
        axis = np.asarray(axis)
        index = int(np.argmin(abs(axis-value)))
        if not np.isclose(axis[index], value, rtol=0, atol=1e-10):
            raise ValueError('uniform layered grid is not boundary aligned; use geometry_conformal mode')
        indices.append(index)
    x0, x1, y0, y1 = indices
    return slice(y0, y1), slice(x0, x1)


def material_grids(case):
    from .model import parse_rect
    owner = np.full((case.ny, case.nx), -1, dtype=int)
    for i, die in enumerate(case.dies):
        owner[rectangle_slice(case, die.bounds)] = i
    masks, conductivities, contacts = [], [], []
    indices = {d.id: i for i, d in enumerate(case.dies)}
    for layer in case.thermal['layers']:
        mask = np.ones_like(owner, dtype=bool)
        if layer['footprint'] == 'chiplets':
            mask = owner >= 0
        elif layer['footprint'] == 'rectangle':
            mask[:] = False
            mask[rectangle_slice(case, parse_rect(layer['rect_mm']))] = True
        k = np.broadcast_to(np.asarray(conductivity_xyz(layer), dtype=float)[:, None, None],
                            (3, case.ny, case.nx)).copy()
        for name, material in layer.get('die_materials', {}).items():
            k[:, owner == indices[name]] = np.asarray(conductivity_xyz(material))[:, None]
        masks.append(mask)
        conductivities.append(k)
        contacts.append({tuple(sorted(indices[name] for name in entry['dies'])): entry['resistance_m2k_w']
                         for entry in layer.get('sidewall_contacts', [])})
    return owner, masks, conductivities, contacts


def assemble_package(case, power):
    cfg = case.thermal
    layers = cfg["layers"]
    dx, dy = case.mesh.widths_mm*1e-3, case.mesh.heights_mm*1e-3
    owner, masks, conductivities, contacts = material_grids(case)
    ids = np.full((len(layers), case.ny, case.nx), -1, dtype=int)
    nodes = []
    for z, layer in enumerate(layers):
        mask = masks[z]
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
        kx, ky, kz = conductivities[z][:, y, x]
        t = layers[z]["thickness_mm"] * 1e-3
        if z == power_z:
            rhs[a] = power[y, x]
        for zz, yy, xx, axis in ((z, y, x + 1, 'x'), (z, y + 1, x, 'y')):
            if yy < case.ny and xx < case.nx and ids[zz, yy, xx] >= 0:
                contact = 0.0
                if layers[z]['footprint'] == 'chiplets' and owner[y, x] != owner[yy, xx]:
                    pair = tuple(sorted((owner[y, x], owner[yy, xx])))
                    if pair not in contacts[z]:
                        continue  # Independent die sidewalls are adiabatic unless specified.
                    contact = contacts[z][pair]
                g = (t*dy[y]/(dx[x]/(2*kx)+contact+dx[xx]/(2*conductivities[z][0, yy, xx])) if axis == 'x'
                     else t*dx[x]/(dy[y]/(2*ky)+contact+dy[yy]/(2*conductivities[z][1, yy, xx])))
                b = ids[zz, yy, xx]
                rows.extend((a, b)); cols.extend((b, a)); values.extend((-g, -g))
                diagonal[a] += g
                diagonal[b] += g
        if z + 1 < len(layers) and ids[z + 1, y, x] >= 0:
            other = layers[z + 1]
            g = dx[x]*dy[y] / (t/(2*kz) + layers[z].get('contact_resistance_above_m2k_w', 0)
                              + other['thickness_mm']*1e-3/(2*conductivities[z+1][2, y, x]))
            b = ids[z + 1, y, x]
            rows.extend((a, b)); cols.extend((b, a)); values.extend((-g, -g))
            diagonal[a] += g
            diagonal[b] += g
        for boundary, h in ((0, cfg["bottom_h_w_m2k"]), (len(layers) - 1, cfg["top_h_w_m2k"])):
            if z == boundary and h > 0:
                sink[a] += dx[x]*dy[y] / (t/(2*kz) + 1/h)
    rows.extend(range(len(nodes))); cols.extend(range(len(nodes))); values.extend(diagonal + sink)
    matrix = coo_matrix((values, (rows, cols)), shape=(len(nodes), len(nodes))).tocsr()
    return matrix, rhs, sink, nodes, ids, power_z


def checked_solution(matrix, rhs, sink, rise):
    """Reject non-finite, inaccurate or non-conserving solves; returns (residual W, removed W)."""
    residual = float(np.max(np.abs(matrix @ rise - rhs))) if np.all(np.isfinite(rise)) else np.inf
    removed = float(sink @ rise) if np.isfinite(residual) else np.nan
    if not np.isfinite(residual) or residual > 1e-8 or not abs(removed - rhs.sum()) <= max(1e-10, 1e-8 * rhs.sum()):
        raise ValueError("package failed finite solution, residual or energy check")
    return residual, removed


def solve_package(case, power, *, timings_s=None):
    started = perf_counter()
    matrix, rhs, sink, nodes, ids, power_z = assemble_package(case, power)
    assembled = perf_counter()
    rise = spsolve(matrix, rhs)
    solved = perf_counter()
    if timings_s is not None:
        timings_s['matrix_assembly_s'] = assembled - started
        timings_s['thermal_linear_solve_s'] = solved - assembled
    residual, removed = checked_solution(matrix, rhs, sink, rise)
    temperature = np.full((case.ny, case.nx), np.nan)
    source = ids[power_z] >= 0
    temperature[source] = rise[ids[power_z][source]] + case.thermal["ambient_c"]
    summary = {"model": case.thermal["model"], "calibration": "not_calibrated",
               "provenance": case.thermal["provenance"], "reported_layer": case.thermal["power_layer"],
               "peak_c": float(np.nanmax(temperature)), "minimum_c": float(np.nanmin(temperature)),
               "mean_c": float(np.average(temperature[source], weights=case.mesh.areas_mm2[source])), "removed_heat_w": removed,
               "energy_balance_error_w": float(removed - rhs.sum()), "linear_residual_inf_w": residual,
               "node_count": len(nodes), "all_node_temperature_c": (rise + case.thermal["ambient_c"]).tolist(),
               "node_indices_layer_y_x": nodes, 'mesh': case.mesh.record(),
               'temperature_location': 'power_layer_cell_centres_not_measured_junction',
               'die_sidewalls': 'adiabatic_unless_explicit_pair_contact',
               'interface_model': 'half_cell_series_resistance_plus_explicit_contact_resistance'}
    return temperature, summary
