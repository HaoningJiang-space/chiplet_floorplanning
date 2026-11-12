"""Exact observation operators for a passive thermal network.

The operator specifies a comparison convention, not recovered logger timing.
All energies cover N complete, piecewise-constant input intervals.
"""

import numpy as np
from scipy.linalg import eigh
from scipy.optimize import least_squares
from scipy.signal import lfilter

from .measured_thermal import STARTS, rank_report
from .measured_transient import CAPACITY_STARTS, LOWER5, UPPER5, matrices, observations

OPERATORS = ('begin', 'end', 'average')
PARAMETERS = ('g_xy_w_per_k', 'g_z_w_per_k', 'g_a_w_per_k',
              'c_cell_j_per_k', 'c_bath_j_per_k')


def propagate(g, c, power, initial, dt_s, operator='end', ledger=False):
    """Solve C dT/dt + G T = P; temperatures are relative to the boundary."""
    g, c, p, initial = map(lambda x: np.asarray(x, dtype=float), (g, c, power, initial))
    n = len(c)
    if (operator not in OPERATORS or not np.isfinite(dt_s) or dt_s <= 0
            or g.shape != (n, n) or initial.shape != (n,) or p.ndim != 2
            or p.shape[1] != n or len(p) == 0 or np.any(c <= 0)
            or not all(np.all(np.isfinite(x)) for x in (g, c, p, initial))
            or not np.allclose(g, g.T, rtol=1e-12, atol=1e-12)):
        raise ValueError('invalid passive-network observation inputs')
    off_diagonal = g - np.diag(np.diag(g))
    if np.any(off_diagonal > 1e-12) or np.any(g.sum(axis=1) < -1e-12):
        raise ValueError('conductance must have nonnegative boundary connections')
    rates, w = eigh(g, np.diag(c))
    if rates.min() <= 0:
        raise ValueError('network must be anchored to a thermal boundary')
    z0, u = w.T @ (c * initial), p @ w
    x = rates * dt_s
    decay = np.exp(-x)
    b = -np.expm1(-x) / rates
    # Integral of a constant forcing response; series avoids cancellation
    # of dt-b for slow modes relative to the observation interval.
    small = x < 1e-3
    d = np.empty_like(x)
    d[~small] = (dt_s - b[~small]) / rates[~small]
    xs = x[small]
    d[small] = dt_s**2 * (0.5 - xs/6 + xs**2/24 - xs**3/120 + xs**4/720)
    z = np.empty((len(p), n))
    for j in range(n):
        z[:, j], _ = lfilter([0., b[j]], [1., -decay[j]], u[:, j], zi=[z0[j]])
    final_z = decay * z[-1] + b * u[-1]
    if operator == 'begin':
        values = z
    elif operator == 'end':
        values = decay * z + b * u
    else:
        values = (b * z + d * u) / dt_s
    details = dict(fastest_time_constant_s=float(1/rates.max()),
                   slowest_time_constant_s=float(1/rates.min()))
    if ledger:
        integral = (b * z.sum(axis=0) + d * u.sum(axis=0)) @ w.T
        final = final_z @ w.T
        supplied = float(p.sum() * dt_s)
        stored = float(c @ (final - initial))
        removed = float(g.sum(axis=0) @ integral)
        error = supplied - stored - removed
        interval_input = p.sum(axis=1)*dt_s
        interval_storage = (np.expm1(-x)*z + b*u) @ (w.T @ c)
        interval_removed = (b*z + d*u) @ (w.T @ g.sum(axis=0))
        interval_error = interval_input - interval_storage - interval_removed
        details.update(interval_count=len(p), duration_s=len(p)*dt_s,
                       input_energy_j=supplied, storage_change_j=stored,
                       removed_heat_j=removed, energy_balance_error_j=error,
                       normalized_energy_residual=abs(error)/max(1., abs(supplied)),
                       max_interval_energy_error_j=float(np.abs(interval_error).max()),
                       max_normalized_interval_energy_residual=float(np.max(np.abs(interval_error)/np.maximum(1., np.abs(interval_input)))),
                       numerical_energy_screen=bool(abs(error) < 1e-7*max(1., abs(supplied))
                                                    and np.all(np.abs(interval_error) < 1e-7*np.maximum(1., np.abs(interval_input)))))
    return values @ w.T, details


def simulate(log_params, power, initial_cells_k, operator='end', ledger=False):
    p = np.asarray(power, dtype=float)
    cells = np.asarray(initial_cells_k, dtype=float)
    if p.ndim != 2 or p.shape[1] != 16 or len(p) < 1 or cells.shape != (16,):
        raise ValueError('expected sixteen input and sensor channels')
    g, c, _ = matrices(log_params)
    # Preserve the earlier conditional initialization, now explicitly labeled
    # as a pre-interval state assumption. No hidden fit of a time shift.
    bath = cells.mean() - np.mean(p[:10]) / np.exp(log_params[1])
    theta, details = propagate(g, c, np.c_[p, np.zeros(len(p))],
                               np.r_[cells, bath], .1, operator, ledger)
    details['initial_bath_rise_k'] = float(bath)
    return theta, details


def raw_metrics(error):
    e = np.asarray(error, dtype=float)
    if e.size == 0 or not np.all(np.isfinite(e)):
        raise ValueError('metrics require nonempty finite residuals')
    return dict(sample_count=int(e.shape[0]), mae_k=float(np.abs(e).mean()),
                rmse_k=float(np.sqrt(np.mean(e**2))), bias_k=float(e.mean()),
                max_abs_error_k=float(np.abs(e).max()))


def residual(params, cases):
    parts = []
    for case in cases:
        theta, _ = simulate(params, case['power_w'], case['initial_cells_k'])
        ix = observations(case)
        error = theta[ix, :16] - case['temperature_rise_k'][ix]
        parts.append(error.ravel() / np.sqrt(error.size))
    return np.concatenate(parts)


def fit(cases, progress=None):
    runs = []
    for index, (g, cap) in enumerate(zip(STARTS, CAPACITY_STARTS)):
        fitted = least_squares(residual, np.log([*g, *cap]), args=(cases,),
                               bounds=(LOWER5, UPPER5), max_nfev=200,
                               xtol=1e-8, ftol=1e-8, gtol=1e-8)
        record = dict(start_index=index, success=bool(fitted.success), status=int(fitted.status),
                      message=fitted.message, cost_k2=float(fitted.cost), nfev=fitted.nfev,
                      parameters=np.exp(fitted.x).tolist(),
                      bound_hit=bool(np.any(np.minimum(fitted.x-LOWER5, UPPER5-fitted.x) < 1e-4)))
        runs.append((fitted, record))
        if progress:
            progress(record)
    best = min(runs, key=lambda item: item[0].cost)[0]
    return best.x, dict(parameters=dict(zip(PARAMETERS, np.exp(best.x).tolist())),
                        multistart=[r for _, r in runs], sensitivity=rank_report(best.jac),
                        optimizer_success=bool(best.success),
                        bound_hit=bool(np.any(np.minimum(best.x-LOWER5, UPPER5-best.x) < 1e-4)))
