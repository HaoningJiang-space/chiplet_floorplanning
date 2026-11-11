"""Measured TTC endpoint adapter and a deliberately limited passive reduction."""

import re
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import csr_matrix

from .physical_invariants import heat_ledger

CALIBRATION = ('one', 'four', 'sixteen', 'line_1')
GROUP_HZ = {'chip': 1000, 'heatsink': 10, 'heatsink_with_fan': 10}
STARTS = ((.05, .1, 1), (1, 1, 1), (.01, 1, .1), (1, .01, 10))
LOWER = np.log([1e-4, 1e-4, 1e-3])
UPPER = np.log([100., 100., 100.])


def patterns():
    result = {}
    for name, count in [('one', 1), ('four', 2), ('nine', 3), ('sixteen', 4)]:
        p = np.full((4, 4), .2)
        p[:count, :count] = 3
        result[name] = p.ravel()
    for name, rows in [('line_1', [0]), ('line_2', [1]),
                       ('thickline_1', [0, 1]), ('thickline_2', [1, 2])]:
        p = np.full((4, 4), .2)
        p[rows] = 3
        result[name] = p.ravel()
    p = np.full((4, 4), .2)
    p[np.indices((4, 4)).sum(axis=0) % 2 == 1] = 3
    result['checkboard'] = p.ravel()
    for name, index in [('hotspot_1', 1), ('hotspot_2', 0),
                        ('hotspot_3', 4), ('hotspot_4', 5)]:
        p = np.full(16, .2)
        p[index] = 7
        result[name] = p
    return result


def ambient_values(path):
    return {name: float(value) for name, value in re.findall(
        r'^(\w+)\s+Tamb=([\d.]+)', Path(path).read_text(encoding='utf-8'), re.M)}


def read_trace(path):
    # Source .sce files use whitespace fscanfMat, despite the .csv extension.
    a = np.loadtxt(path)
    if a.ndim != 2 or a.shape[1] != 49 or not np.all(np.isfinite(a)):
        raise ValueError('TTC expects 49 finite columns; last auxiliary column is not a sensor')
    if np.any(a[:, 32:48] <= -273.15):
        raise ValueError('invalid absolute temperature')
    # Signed near-zero current readout is measurement noise, not clipped heat.
    # The authors' plotting scripts consume only columns 1..48; preserve the
    # undocumented column 49 in the immutable source without interpreting it.
    return a[:, :16], a[:, 16:32], a[:, 32:48]


def longest_interval(mask):
    edges = np.diff(np.r_[False, np.asarray(mask, dtype=bool), False].astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    if not len(starts):
        raise ValueError('no high-power interval')
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i])  # half-open


def endpoint(v, i, t, nominal, hz):
    power = v * i
    threshold = (3.2 + float(np.sum(nominal))) / 2
    begin, end = longest_interval(power.sum(axis=1) > threshold)
    if end - begin < 120 * hz:
        return dict(eligible=False, reason='activation shorter than 120 s',
                    activation_start_index=begin, activation_end_exclusive=end)
    start = end - 60 * hz
    p, y = power[start:end], t[start:end]
    clock = np.arange(len(y), dtype=float) / hz
    clock -= clock.mean()
    slopes = clock @ (y - y.mean(axis=0)) / (clock @ clock)
    n = 20 * hz
    drift = y[-n:].mean(axis=0) - y[:n].mean(axis=0)
    pdrift = (p[-n:].sum(axis=1).mean() - p[:n].sum(axis=1).mean()) / p.sum(axis=1).mean()
    mean_p = p.mean(axis=0)
    screen = dict(slope=bool(np.max(np.abs(slopes)) <= .002),
                  temperature_drift=bool(np.max(np.abs(drift)) <= .25),
                  power_drift=bool(abs(pdrift) <= .02))
    return dict(eligible=all(screen.values()), quasi_steady_screens=screen,
                activation_start_index=begin, activation_end_exclusive=end,
                window_start_index=start, window_end_exclusive=end, window_duration_s=60,
                power_w=mean_p.tolist(), temperature_c=y.mean(axis=0).tolist(),
                temperature_std_k=y.std(axis=0).tolist(),
                slope_k_per_s=slopes.tolist(), temperature_drift_k=drift.tolist(),
                relative_total_power_drift=float(pdrift),
                nominal_pattern_relative_rms=float(np.linalg.norm(mean_p - nominal) / np.linalg.norm(nominal)),
                measured_total_power_w=float(mean_p.sum()),
                nominal_total_power_w=float(np.sum(nominal)))


def laplacian():
    a = np.zeros((16, 16))
    for row in range(4):
        for col in range(4):
            node = 4 * row + col
            for other in ([node + 1] if col < 3 else []) + ([node + 4] if row < 3 else []):
                a[node, node] += 1
                a[other, other] += 1
                a[node, other] -= 1
                a[other, node] -= 1
    return a


LAPLACIAN = laplacian()


def predict(log_g, power):
    gx, gz, ga = np.exp(log_g)
    p = np.asarray(power, dtype=float)
    if p.shape[-1] != 16 or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError('invalid source vector')
    local = np.linalg.solve(gx * LAPLACIAN + gz * np.eye(16), p.T).T
    return local + p.sum(axis=-1, keepdims=True) / ga


def sensitivity(log_g, power):
    gx, gz, ga = np.exp(log_g)
    p = np.atleast_2d(power)
    a = gx * LAPLACIAN + gz * np.eye(16)
    x = np.linalg.solve(a, p.T)
    return np.stack((-np.linalg.solve(a, gx * LAPLACIAN @ x).T,
                     -np.linalg.solve(a, gz * x).T,
                     np.broadcast_to(-p.sum(axis=1, keepdims=True) / ga, p.shape)), axis=-1).reshape(-1, 3)


def rank_report(jac):
    s = np.linalg.svd(jac, compute_uv=False)
    rank = int(np.count_nonzero(s > s[0] * 1e-6)) if s[0] else 0
    return dict(singular_values=s.tolist(), relative_rank_threshold=1e-6,
                rank=rank, full_column_rank=rank == jac.shape[1],
                condition_number=float(s[0] / s[-1]) if rank == jac.shape[1] else None)


def fit(power, rise):
    p, y = np.asarray(power), np.asarray(rise)
    runs = []
    for initial in STARTS:
        r = least_squares(lambda z: (predict(z, p) - y).ravel(), np.log(initial),
                          jac=lambda z: sensitivity(z, p), bounds=(LOWER, UPPER),
                          xtol=1e-12, ftol=1e-12, gtol=1e-10, max_nfev=2000)
        runs.append(r)
    best = min(runs, key=lambda r: r.cost)
    return best.x, dict(g_xy_w_per_k=float(np.exp(best.x[0])),
                        g_z_w_per_k=float(np.exp(best.x[1])),
                        g_a_w_per_k=float(np.exp(best.x[2])),
                        train_rmse_k=float(np.sqrt(np.mean(best.fun**2))),
                        bound_hit=bool(np.any(np.minimum(best.x - LOWER, UPPER - best.x) < 1e-4)),
                        sensitivity=rank_report(sensitivity(best.x, p)),
                        uniform_source_control=rank_report(sensitivity(best.x, np.full((1, 16), 3.))),
                        multistart=[dict(success=bool(r.success), cost_k2=float(r.cost),
                                         conductance_w_per_k=np.exp(r.x).tolist(), nfev=r.nfev) for r in runs])


def network_ledger(log_g, p, ambient_c):
    gx, gz, ga = np.exp(log_g)
    g = np.zeros((17, 17))
    g[:16, :16] = gx * LAPLACIAN + gz * np.eye(16)
    g[:16, 16] = g[16, :16] = -gz
    g[16, 16] = 16 * gz + ga
    sink = np.r_[np.zeros(16), ga]
    rise = np.r_[predict(log_g, np.asarray(p)), np.sum(p) / ga]
    result = heat_ledger(csr_matrix(g), sink, rise + ambient_c + 273.15,
                         ambient_c + 273.15, np.r_[p, 0.])
    result['minimum_eigenvalue_w_per_k'] = float(np.linalg.eigvalsh(g).min())
    return result
