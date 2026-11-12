"""Exact separated steady solve of the declared layered TTC FV equations.

All discrete lateral modes are retained; this is not a reduced-order model.
Homogeneous layers on the SAME lateral mesh and a spatially uniform bath are
essential. This solver must not be applied to lateral material heterogeneity.
"""

import numpy as np
from scipy.linalg import eigh_tridiagonal

from .ttc_spatial import axis, weights
from .ttc_spectral import impedance


def lateral(edges):
    """Mass-orthonormal Neumann FV modes: L v = lambda diag(width) v."""
    edges = np.asarray(edges, dtype=float)
    width = np.diff(edges)
    if edges.ndim != 1 or not np.all(np.isfinite(edges)) or not len(width) or np.any(width <= 0):
        raise ValueError('finite increasing axis required')
    face = 2 / (width[:-1] + width[1:])
    diagonal = np.r_[face, 0.] + np.r_[0., face]
    d = diagonal / width
    e = -face / np.sqrt(width[:-1] * width[1:])
    if len(width) == 1:
        values, q = np.zeros(1), np.ones((1, 1))
    else:
        values, q = eigh_tridiagonal(d, e)
    scale = max(1., float(np.max(abs(d))) + 2 * float(np.max(abs(e), initial=0.)))
    tolerance = 100 * np.finfo(float).eps * scale
    if abs(values[0]) > tolerance or (len(values) > 1 and values[1] <= tolerance):
        raise ValueError('invalid zero mode or unresolved positive lateral mode')
    # Analytic constant mode, checked below. Never clip nonzero eigenvalues.
    values[0] = 0.
    q[:, 0] = np.sqrt(width / width.sum())
    aq = d[:, None] * q
    aq[:-1] += e[:, None] * q[1:]
    aq[1:] += e[:, None] * q[:-1]
    residual = float(np.max(abs(aq - q * values)) / scale)
    orthogonality = float(np.max(abs(q.T @ q - np.eye(len(width)))))
    if residual > 1e-11 or orthogonality > 1e-10:
        raise ValueError('lateral eigensystem failed residual/orthogonality checks')
    return values, q / np.sqrt(width)[:, None], dict(
        normalized_eigen_residual=residual, mass_orthogonality_error=orthogonality,
        smallest_positive_eigenvalue_per_m2=float(values[1]) if len(values) > 1 else None)


def vertical(lambdas, dz, k, source_fraction):
    """Batched tridiagonal solve; output z-cell response per modal W/m²."""
    lambdas, dz, k, source_fraction = [np.asarray(v, dtype=float) for v in
                                      (lambdas, dz, k, source_fraction)]
    if (any(v.ndim != 1 or not np.all(np.isfinite(v)) for v in (lambdas, dz, k, source_fraction))
            or not len(lambdas) or not len(dz) or len(dz) != len(k) or len(dz) != len(source_fraction)
            or np.any(lambdas < 0) or np.any(dz <= 0) or np.any(k <= 0)
            or np.any(source_fraction < 0) or not np.isclose(source_fraction.sum(), 1., atol=1e-12, rtol=0)):
        raise ValueError('invalid passive modal stack or source fractions')
    face = 1 / (dz[:-1] / (2 * k[:-1]) + dz[1:] / (2 * k[1:]))
    top = 2 * k[-1] / dz[-1]
    diagonal = k[:, None] * dz[:, None] * lambdas[None, :]
    diagonal[:-1] += face[:, None]
    diagonal[1:] += face[:, None]
    diagonal[-1] += top
    pivots = diagonal.copy()
    solution = np.broadcast_to(source_fraction[:, None], diagonal.shape).copy()
    for i in range(1, len(dz)):
        ratio = -face[i-1] / pivots[i-1]
        pivots[i] -= ratio * (-face[i-1])
        solution[i] -= ratio * solution[i-1]
    if not np.all(np.isfinite(pivots)) or np.any(pivots <= 0):
        raise ValueError('nonpositive modal elimination pivot')
    solution[-1] /= pivots[-1]
    for i in range(len(dz)-2, -1, -1):
        solution[i] = (solution[i] + face[i] * solution[i+1]) / pivots[i]
    residual = diagonal * solution - source_fraction[:, None]
    residual[:-1] -= face[:, None] * solution[1:]
    residual[1:] -= face[:, None] * solution[:-1]
    # Backward error uses each equation's actual term magnitudes.
    norm = abs(diagonal * solution) + source_fraction[:, None]
    norm[:-1] += abs(face[:, None] * solution[1:])
    norm[1:] += abs(face[:, None] * solution[:-1])
    backward_error = float(np.max(abs(residual) / np.maximum(norm, np.finfo(float).tiny)))
    if backward_error > 1e-11:
        raise ValueError('vertical solve failed normalized residual')
    base_diagonal = np.r_[face, 0.] + np.r_[0., face]
    base_diagonal[-1] += top
    if len(dz) == 1:
        base_eigen = base_diagonal
    else:
        base_eigen = eigh_tridiagonal(base_diagonal, -face, eigvals_only=True)
    if base_eigen[0] <= 0:
        raise ValueError('unanchored vertical system')
    # Weyl bounds for every mode of A(lambda)=A(0)+lambda*diag(k*dz).
    # The ratio is monotone in lambda, so endpoints bound all retained modes.
    endpoints = np.array([lambdas.min(), lambdas.max()])
    condition_bound = np.max((base_eigen[-1]+endpoints*np.max(k*dz)) /
                             (base_eigen[0]+endpoints*np.min(k*dz)))
    return solution, dict(max_vertical_backward_error=backward_error,
                          max_vertical_absolute_residual=float(np.max(abs(residual))),
                          all_mode_condition_number_upper_bound=float(condition_bound))


def configuration(geometry, group, pitch_um, active_cells, bulk_cells, pad_cells):
    counts = (active_cells, bulk_cells, pad_cells)
    if group not in ('heatsink', 'heatsink_with_fan') or any(c < 1 or int(c) != c for c in counts):
        raise ValueError('valid cooling group and positive integer subdivisions required')
    heaters = geometry['heaters']
    side = geometry['die_side_um']
    x = axis([0., side] + [v for r in heaters for v in (r['x_um'], r['x_um'] + r['width_um'])], pitch_um)
    y = axis([0., side] + [v for r in heaters for v in (r['y_um'], r['y_um'] + r['height_um'])], pitch_um)
    dz = np.concatenate([np.full(c, geometry[key] * 1e-6 / c) for c, key in
                         zip(counts, ('active_silicon_um', 'bulk_silicon_um', 'thermal_pad_um'))])
    mat = geometry['materials']['natural' if group == 'heatsink' else 'fan']
    k = np.r_[np.full(active_cells + bulk_cells, mat['SILICON']['conductivity_w_per_m_k']),
              np.full(pad_cells, mat['SILICONE']['conductivity_w_per_m_k'])]
    source = np.r_[np.full(active_cells, 1 / active_cells), np.zeros(bulk_cells + pad_cells)]
    return x, y, dz, k, source


def planar_mappings(geometry, x, y):
    """Physical W/W per cell and point observation, independent of modes."""
    b = np.zeros((len(y)-1, len(x)-1, 16))
    for heater in geometry['heaters']:
        hx, hy, width, height = [heater[key] * 1e-6 for key in ('x_um', 'y_um', 'width_um', 'height_um')]
        ax = np.maximum(0., np.minimum(x[1:], hx+width) - np.maximum(x[:-1], hx))
        ay = np.maximum(0., np.minimum(y[1:], hy+height) - np.maximum(y[:-1], hy))
        b[:, :, heater['power_index']] += np.outer(ay, ax) / (width*height) * heater['power_fraction']
    h = np.zeros((16, len(y)-1, len(x)-1))
    for s, (sx, sy) in enumerate(np.array(geometry['sensors_xy_um']) * 1e-6):
        for ix, wx in weights((x[:-1]+x[1:])/2, sx):
            for iy, wy in weights((y[:-1]+y[1:])/2, sy):
                h[s, iy, ix] += wx*wy
    if not np.allclose(b.sum(axis=(0, 1)), 1., atol=1e-12, rtol=0) or not np.allclose(h.sum(axis=(1, 2)), 1., atol=1e-12, rtol=0):
        raise ValueError('nonconservative source or observation mapping')
    return b, h


def transfer(geometry, group, ga, pitch_um=500., active_cells=1, bulk_cells=2, pad_cells=2):
    """Return 16x16 steady K/W transfer and numerical diagnostics."""
    if not np.isfinite(ga) or ga <= 0:
        raise ValueError('positive finite sink conductance required')
    x, y, dz, k, source = configuration(geometry, group, pitch_um, active_cells, bulk_cells, pad_cells)
    lx, vx, ex = lateral(x)
    ly, vy, ey = lateral(y)
    lambdas = (ly[:, None] + lx[None, :]).ravel()
    planar_b, planar_h = planar_mappings(geometry, x, y)
    bmode = np.einsum('yi,yxc,xj->ijc', vy, planar_b, vx, optimize=True).reshape(-1, 16)
    hmode = np.einsum('yi,cyx,xj->cij', vy, planar_h, vx, optimize=True).reshape(16, -1)
    zv, ez = vertical(lambdas, dz, k, source)
    centers_z = np.cumsum(dz) - dz/2
    zw = weights(centers_z, geometry['active_silicon_um'] * 1e-6 / 2)
    zsensor = sum(w*zv[i] for i, w in zw)
    result = hmode @ (zsensor[:, None] * bmode) + 1/ga
    # Continuous z on the same discrete lateral operator isolates depth error.
    mat = geometry['materials']['natural' if group == 'heatsink' else 'fan']
    zexact = impedance(np.sqrt(lambdas), geometry['active_silicon_um']*1e-6,
                       geometry['bulk_silicon_um']*1e-6, geometry['thermal_pad_um']*1e-6,
                       mat['SILICON']['conductivity_w_per_m_k'], mat['SILICONE']['conductivity_w_per_m_k'])
    zcontinuum = hmode @ (zexact[:, None]*bmode) + 1/ga
    area = (x[-1]-x[0]) * (y[-1]-y[0])
    # For the uniform mode every watt must leave the top boundary.
    heat_error = abs(2*k[-1]/dz[-1] * zv[-1, 0] - 1.)
    mode_source_error = float(np.max(abs(bmode[0] * np.sqrt(area) - 1.)))
    mode_sensor_error = float(np.max(abs(hmode[:, 0] * np.sqrt(area) - 1.)))
    return result, dict(nx=len(x)-1, ny=len(y)-1, nz=len(dz),
                        equivalent_3d_nodes=(len(x)-1)*(len(y)-1)*len(dz)+1,
                        lateral_modes_retained=len(lambdas), x_eigensystem=ex, y_eigensystem=ey,
                        vertical=ez, zero_mode_heat_balance_error=float(heat_error),
                        constant_source_projection_error=mode_source_error,
                        constant_sensor_projection_error=mode_sensor_error,
                        minimum_transfer_k_per_w=float(result.min()),
                        continuous_z_transfer_k_per_w=zcontinuum.tolist(),
                        physical_model_qualified=False)
