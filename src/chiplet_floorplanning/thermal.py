"""Cell-centred finite volume solver for a uniform slab with distributed sink.

This is an uncalibrated numerical reference, not a multilayer package solver.
Side boundaries are adiabatic; each cell exchanges heat with one fixed ambient.
"""

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


def solve_steady(case, power):
    power = np.asarray(power, dtype=float)
    if power.shape != (case.ny, case.nx) or not np.all(np.isfinite(power)) or np.any(power < 0):
        raise ValueError("power must be a finite, nonnegative ny by nx array in watts")
    dx = case.package.width * 1e-3 / case.nx
    dy = case.package.height * 1e-3 / case.ny
    config = case.thermal
    kt = config["conductivity_w_mk"] * config["thickness_mm"] * 1e-3
    gx, gy = kt * dy / dx, kt * dx / dy
    sink = config["sink_h_w_m2k"] * dx * dy
    size = case.nx * case.ny
    diagonal = np.full(size, sink)
    rows, cols, values = [], [], []
    for y in range(case.ny):
        for x in range(case.nx):
            a = y * case.nx + x
            if x + 1 < case.nx:
                b = a + 1
                rows.extend((a, b))
                cols.extend((b, a))
                values.extend((-gx, -gx))
                diagonal[a] += gx
                diagonal[b] += gx
            if y + 1 < case.ny:
                b = a + case.nx
                rows.extend((a, b))
                cols.extend((b, a))
                values.extend((-gy, -gy))
                diagonal[a] += gy
                diagonal[b] += gy
    rows.extend(range(size))
    cols.extend(range(size))
    values.extend(diagonal)
    matrix = coo_matrix((values, (rows, cols)), shape=(size, size)).tocsr()
    rhs = power.ravel()
    rise = spsolve(matrix, rhs)
    residual = float(np.max(np.abs(matrix @ rise - rhs)))
    removed = float(sink * rise.sum())
    total = float(rhs.sum())
    if not np.all(np.isfinite(rise)) or residual > 1e-8 * max(1, total):
        raise ValueError("thermal linear solve failed residual check")
    if abs(removed - total) > 1e-8 * max(1, total):
        raise ValueError("thermal solve failed energy conservation")
    temperature = rise.reshape(power.shape) + config["ambient_c"]
    return temperature, {"model": config["model"], "calibration": "not_calibrated",
                         "provenance": config["provenance"], "peak_c": float(temperature.max()),
                         "minimum_c": float(temperature.min()), "mean_c": float(temperature.mean()),
                         "removed_heat_w": removed, "energy_balance_error_w": removed - total,
                         "linear_residual_inf_w": residual}
