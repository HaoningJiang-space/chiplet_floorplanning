"""Conservative 17-node TTC transient reduction, not material extraction."""

import numpy as np
from scipy.linalg import eigh
from scipy.optimize import least_squares
from scipy.signal import lfilter

from .measured_thermal import LAPLACIAN, STARTS, LOWER, UPPER, rank_report

CAPACITY_STARTS = ((.02, 100), (.1, 1000), (.01, 10), (1, 100))
LOWER5 = np.r_[LOWER, np.log([1e-4, .1])]
UPPER5 = np.r_[UPPER, np.log([10., 10000.])]


def matrices(log_params):
    gx, gz, ga, cc, cb = np.exp(log_params)
    if not np.all(np.isfinite([gx, gz, ga, cc, cb])) or min(gx, gz, ga, cc, cb) <= 0:
        raise ValueError('conductance and capacity must be finite and positive')
    g = np.zeros((17, 17))
    g[:16, :16] = gx * LAPLACIAN + gz * np.eye(16)
    g[:16, 16] = g[16, :16] = -gz
    g[16, 16] = 16 * gz + ga
    c = np.r_[np.full(16, cc), cb]
    return g, c, ga


def simulate(log_params, power, initial_cells_k, dt_s=.1, alternative_initial=False, ledger=False):
    p = np.asarray(power, dtype=float)
    initial_cells = np.asarray(initial_cells_k, dtype=float)
    if (p.ndim != 2 or p.shape[1] != 16 or len(p) < 2 or not np.all(np.isfinite(p))
            or initial_cells.shape != (16,) or not np.all(np.isfinite(initial_cells)) or dt_s <= 0):
        raise ValueError('invalid transient inputs')
    g, c, ga = matrices(log_params)
    gz = np.exp(log_params[1])
    bath0 = initial_cells.mean()
    if not alternative_initial:
        bath0 -= np.mean(p[:max(1, round(1 / dt_s))]) / gz
    initial = np.r_[initial_cells, bath0]
    # eigh returns C-orthonormal eigenvectors: W.T C W=I, W.T G W=diag(rate).
    rates, w = eigh(g, np.diag(c))
    if np.min(rates) <= 0:
        raise ValueError('unstable thermal mode')
    z0 = w.T @ (c * initial)
    u = p @ w[:16]
    decay = np.exp(-rates * dt_s)
    b = -np.expm1(-rates * dt_s) / rates
    z = np.empty((len(p), 17))
    for j in range(17):
        z[:, j], _ = lfilter([0., b[j]], [1., -decay[j]], u[:, j], zi=[z0[j]])
    theta = z @ w.T
    details = dict(initial_bath_rise_k=float(bath0),
                   fastest_time_constant_s=float(1 / rates.max()),
                   slowest_time_constant_s=float(1 / rates.min()))
    if ledger:
        # Integrate each exponential segment analytically, not by a coarse
        # trapezoid that would miss the fast cell modes.
        int_z = z[:-1].sum(axis=0) * b + u[:-1].sum(axis=0) * (dt_s - b) / rates
        input_energy = float(p[:-1].sum() * dt_s)
        delta_storage = float(c @ (theta[-1] - theta[0]))
        removed = float(ga * (int_z @ w[-1]))
        residual = input_energy - delta_storage - removed
        details.update(input_energy_j=input_energy, storage_change_j=delta_storage,
                       removed_heat_j=removed, energy_balance_error_j=residual,
                       normalized_energy_residual=abs(residual) / max(1., abs(input_energy)),
                       numerical_energy_screen=bool(abs(residual) <= 1e-7 * max(1., abs(input_energy))))
    return theta, details


def observations(case):
    return np.unique(np.r_[np.arange(0, len(case['power_w']), 10), len(case['power_w']) - 1])


def residual(log_params, cases):
    errors = []
    for c in cases:
        theta, _ = simulate(log_params, c['power_w'], c['initial_cells_k'])
        ix = observations(c)
        err = theta[ix, :16] - c['temperature_rise_k'][ix]
        errors.append(err.ravel() / np.sqrt(err.size))
    return np.concatenate(errors)


def fit(cases, progress=None):
    runs = []
    for index, (g, cap) in enumerate(zip(STARTS, CAPACITY_STARTS)):
        result = least_squares(residual, np.log([*g, *cap]), args=(cases,),
                               bounds=(LOWER5, UPPER5), max_nfev=200,
                               xtol=1e-8, ftol=1e-8, gtol=1e-8)
        record = dict(start_index=index, success=bool(result.success), status=int(result.status),
                      message=str(result.message), cost_k2=float(result.cost), nfev=result.nfev,
                      parameters=np.exp(result.x).tolist(),
                      bound_hit=bool(np.any(np.minimum(result.x - LOWER5, UPPER5 - result.x) < 1e-4)))
        runs.append((result, record))
        if progress:
            progress(record)
    best, _ = min(runs, key=lambda item: item[0].cost)
    return best.x, dict(parameters=dict(zip(['g_xy_w_per_k', 'g_z_w_per_k', 'g_a_w_per_k',
                                            'c_cell_j_per_k', 'c_bath_j_per_k'], np.exp(best.x).tolist())),
                        multistart=[r for _, r in runs],
                        sensitivity=rank_report(best.jac),
                        bound_hit=bool(np.any(np.minimum(best.x - LOWER5, UPPER5 - best.x) < 1e-4)),
                        optimizer_success=bool(best.success))
