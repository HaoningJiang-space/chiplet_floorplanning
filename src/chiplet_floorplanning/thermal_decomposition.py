"""Independent source solves on an unchanged linear package thermal network."""

import hashlib

import numpy as np
from scipy.sparse.linalg import spsolve

from .package import assemble_package, material_grids
from .power import rasterize


def matrix_digest(matrix):
    digest = hashlib.sha256()
    for array in (
        np.asarray(matrix.shape, dtype=np.int64),
        matrix.indptr,
        matrix.indices,
        matrix.data,
    ):
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def decompose_sources(case):
    """Preserve passive dies; independently solve the full RHS and each source.

    Supported only for the constant-property, linear, steady layered model.
    Reassembly verifies that source removal does not change conductance.
    """
    if case.thermal["model"] != "layered_package_steady":
        raise ValueError(
            "source decomposition requires the linear layered package model"
        )
    names = [d.id for d in case.dies]
    if "total" in names:
        raise ValueError("die ID 'total' is reserved for thermal decomposition")
    power, _ = rasterize(case)
    owner, _, _, _ = material_grids(case)
    matrix, rhs, sink, nodes, ids, z = assemble_package(case, power)
    total = spsolve(matrix, rhs)
    fields = {"total": total}
    checks, source_powers = [], {}
    base_hash = matrix_digest(matrix)
    for i, die in enumerate(case.dies):
        isolated = np.where(owner == i, power, 0.0)
        other, b, other_sink, other_nodes, other_ids, other_z = assemble_package(
            case, isolated
        )
        same = (
            base_hash == matrix_digest(other)
            and nodes == other_nodes
            and np.array_equal(ids, other_ids)
            and np.array_equal(sink, other_sink)
            and z == other_z
        )
        if not same:
            raise ValueError("changing only power changed the material thermal network")
        fields[die.id] = spsolve(other, b)
        source_powers[die.id] = float(b.sum())
        checks.append(
            dict(
                source=die.id,
                material_network_identical=True,
                linear_residual_inf_w=float(np.max(np.abs(other @ fields[die.id] - b))),
                energy_balance_error_w=float(other_sink @ fields[die.id] - b.sum()),
            )
        )
    full_residual = float(np.max(np.abs(matrix @ total - rhs)))
    full_balance = float(sink @ total - rhs.sum())
    error = float(np.max(np.abs(total - sum(fields[n] for n in names))))
    if (
        not all(np.all(np.isfinite(v)) for v in fields.values())
        or min(float(v.min()) for v in fields.values()) < -1e-8
        or error > 1e-8
        or full_residual > 1e-8
        or abs(full_balance) > 3e-8
        or any(
            c["linear_residual_inf_w"] > 1e-8 or abs(c["energy_balance_error_w"]) > 3e-8
            for c in checks
        )
    ):
        raise ValueError(
            "thermal source decomposition failed conservation/linearity checks"
        )
    source_nodes = ids[z][ids[z] >= 0]
    hotspot = int(source_nodes[np.argmax(total[source_nodes])])

    def at_hotspot(node):
        zz, yy, xx = nodes[node]
        contributions = {name: float(fields[name][node]) for name in names}
        die_index = int(owner[yy, xx])
        return dict(
            node_index=node,
            layer=case.thermal["layers"][zz]["id"],
            cell_y_x=[yy, xx],
            x_mm=float(case.mesh.x_centers_mm[xx]),
            y_mm=float(case.mesh.y_centers_mm[yy]),
            die_id=names[die_index] if die_index >= 0 else None,
            temperature_c=float(total[node] + case.thermal["ambient_c"]),
            total_rise_k=float(total[node]),
            source_contributions_k=contributions,
            source_pattern_response_k_per_w={
                n: contributions[n] / source_powers[n] if source_powers[n] > 0 else None
                for n in names
            },
        )

    die_hotspots = {}
    for i, die in enumerate(case.dies):
        active = ids[z][(owner == i) & (ids[z] >= 0)]
        if not len(active):
            raise ValueError("die has no material in reported power layer")
        die_hotspots[die.id] = at_hotspot(int(active[np.argmax(total[active])]))
    report = dict(
        source_powers_w=source_powers,
        total_power_w=float(rhs.sum()),
        material_node_count=len(nodes),
        matrix_sha256=base_hash,
        all_source_matrices_identical=True,
        all_node_superposition_error_k=error,
        total_linear_residual_inf_w=full_residual,
        total_energy_balance_error_w=full_balance,
        source_checks=checks,
        total_hotspot=at_hotspot(hotspot),
        die_hotspots=die_hotspots,
        independent_source_peak_rises_k={
            n: float(np.max(fields[n][source_nodes])) for n in names
        },
        scope="constant-property linear steady model; same-hotspot source contributions, not physical calibration",
    )
    grids = {}
    for name, values in fields.items():
        grid = np.full((case.ny, case.nx), np.nan)
        active = ids[z] >= 0
        grid[active] = values[ids[z][active]]
        grids[name] = grid
    return report, grids
