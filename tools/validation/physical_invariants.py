"""Necessary passive-network conditions; these cannot establish model fidelity."""

import numpy as np
from scipy.sparse import diags, triu
from scipy.sparse.csgraph import connected_components


def passive_conductance(matrix, sink):
    matrix = matrix.tocsr()
    sink = np.asarray(sink, dtype=float)
    if matrix.shape != (len(sink), len(sink)) or not len(sink):
        raise ValueError('conductance shape mismatch')
    if not np.all(np.isfinite(matrix.data)) or not np.all(np.isfinite(sink)):
        raise ValueError('nonfinite conductance')
    scale = max(1.0, float(np.max(np.abs(matrix.data), initial=0)))
    tolerance = 1e-12 * scale
    asymmetry = matrix - matrix.T
    symmetry_error = float(np.max(np.abs(asymmetry.data), initial=0))
    off = matrix - diags(matrix.diagonal())
    row_error = float(np.max(np.abs(np.asarray(matrix.sum(axis=1)).ravel() - sink)))
    if symmetry_error > tolerance or np.any(off.data > tolerance) or np.any(sink < 0) or row_error > tolerance:
        raise ValueError('nonpassive, nonreciprocal or unaccounted conductance')
    graph = off.copy()
    graph.data = (graph.data < 0).astype(float)
    graph.eliminate_zeros()
    count, labels = connected_components(graph, directed=False)
    anchored = all(np.any(sink[labels == component] > 0) for component in range(count))
    if not anchored:
        raise ValueError('unanchored conductance component; no unique steady state')
    return dict(component_count=int(count), every_component_has_sink=anchored,
                symmetry_error_w_per_k=symmetry_error, row_sum_minus_sink_inf_w_per_k=row_error,
                positive_definiteness_basis='nonnegative edges and sinks, with a positive sink in each connected component')


def heat_ledger(matrix, sink, temperature_k, ambient_k, power_w):
    structural = passive_conductance(matrix, sink)
    t = np.asarray(temperature_k, dtype=float)
    power = np.asarray(power_w, dtype=float)
    if (t.shape != (matrix.shape[0],) or power.shape != t.shape
            or not np.all(np.isfinite(t)) or not np.all(np.isfinite(power))
            or not np.isfinite(ambient_k) or np.any(t <= 0) or ambient_k <= 0 or np.any(power < 0)):
        raise ValueError('invalid absolute temperature or heat source')
    edges = triu(-matrix, k=1).tocoo()
    g = edges.data
    delta = t[edges.row] - t[edges.col]
    sigma_internal = g * delta**2 / (t[edges.row] * t[edges.col])
    removed = sink * (t - ambient_k)
    sigma_boundary = removed * (1 / ambient_k - 1 / t)
    balance = float(removed.sum() - power.sum())
    residual = float(np.max(np.abs(matrix @ (t - ambient_k) - power)))
    if abs(balance) > 1e-8 * max(1, power.sum()) or residual > 1e-8 * max(1, power.sum()):
        raise ValueError('heat balance or local equation residual failed')
    if np.min(t) < ambient_k - 1e-9 or np.min(sigma_internal, initial=0) < -1e-12 or np.min(sigma_boundary, initial=0) < -1e-12:
        raise ValueError('maximum principle or entropy production failed')
    return dict(structural, input_power_w=float(power.sum()), removed_heat_w=float(removed.sum()),
                energy_balance_error_w=balance, local_balance_inf_w=residual,
                minimum_rise_k=float(t.min() - ambient_k),
                internal_entropy_production_w_per_k=float(sigma_internal.sum()),
                boundary_entropy_production_w_per_k=float(sigma_boundary.sum()),
                scope='steady discrete conduction/contact/convection to one reservoir; no entropy model for the heat-generating electronics')
