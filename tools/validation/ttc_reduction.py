"""Congruence reduction with explicit per-body physical heat balances."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy.linalg import eigh, qr
from scipy.signal import lfilter
from scipy.sparse import diags
from scipy.sparse.linalg import splu


SHIFTS = ((0., 1.), (0., .01, 1., 100.), (0., .001, .01, .1, 1., 10., 100., 1000.))


def body_basis(capacity, groups):
    """Orthonormal body indicators in coordinates sqrt(C)*temperature."""
    c = np.asarray(capacity)
    covered = np.zeros(len(c), dtype=int)
    q = np.zeros((len(c), len(groups)))
    for index, ids in enumerate(groups):
        ids = np.asarray(ids).ravel()
        covered[ids] += 1
        q[ids, index] = np.sqrt(c[ids]/c[ids].sum())
    if np.any(covered != 1) or np.any(c <= 0) or not np.all(np.isfinite(c)):
        raise ValueError('positive capacities and a disjoint complete body partition required')
    return q


def snapshot_bank(g, c, b, shifts=SHIFTS[-1], progress=None):
    source = b.toarray() if hasattr(b, 'toarray') else np.asarray(b)
    bank = {'instantaneous':source/np.asarray(c)[:, None]}
    audit = []
    for shift in shifts:
        start = perf_counter()
        a = (g+diags(c*shift)).tocsc()
        factor = splu(a)
        solution = factor.solve(source)
        residual = a @ solution-source
        relative = np.linalg.norm(residual, axis=0)/np.linalg.norm(source, axis=0)
        if relative.max() > 1e-7:
            raise ValueError('snapshot solve residual too large')
        bank[shift] = solution
        record = dict(shift_per_s=shift, seconds=perf_counter()-start,
                      max_relative_residual=float(relative.max()), max_absolute_residual=float(abs(residual).max()))
        audit.append(record)
        if progress is not None:
            progress(record)
    return bank, audit


@dataclass
class Reduced:
    rates: np.ndarray
    inputs: np.ndarray
    sensors: np.ndarray
    storage: np.ndarray
    loss: np.ndarray
    body_storage: np.ndarray
    body_flow: np.ndarray
    body_inputs: np.ndarray
    body_capacities: np.ndarray
    source_sums: np.ndarray
    audit: dict
    reconstruction: np.ndarray

    def frequency(self, omega):
        return (self.sensors/(self.rates+1j*omega)) @ self.inputs.T

    def initial(self, power, first_temperature, uniform=False):
        measured_mean = float(np.mean(first_temperature))
        if uniform:
            return self.storage*measured_mean
        equilibrium = (np.mean(power[:10], axis=0) @ self.inputs)/self.rates
        offset = measured_mean-float(np.mean(self.sensors @ equilibrium))
        return equilibrium+offset*self.storage

    def steps(self, powers, times):
        forcing = self.inputs.T @ np.asarray(powers)
        return np.array([self.sensors @ ((-np.expm1(-self.rates*t)/self.rates)[:, None]*forcing) for t in times])

    def run(self, power, initial, dt=.1, chunk_size=2048):
        p, z = np.asarray(power), np.asarray(initial).copy()
        if p.ndim != 2 or p.shape[1] != len(self.source_sums) or z.shape != self.rates.shape or dt <= 0:
            raise ValueError('invalid reduced transient inputs')
        rates = self.rates
        x = rates*dt
        decay = np.exp(-x)
        beta = -np.expm1(-x)/rates
        delta = np.empty_like(rates)
        small = x < 1e-3
        delta[~small] = (dt-beta[~small])/rates[~small]
        xs = x[small]
        delta[small] = dt**2*(.5-xs/6+xs**2/24-xs**3/120+xs**4/720)
        y = np.empty((len(p), self.sensors.shape[0]))
        body_rate = np.empty((len(p), self.body_storage.shape[1]))
        loss_rate = np.empty(len(p))
        mean_rate = np.empty(len(p))
        initial_z = z.copy()
        max_error = 0.; max_block_error = 0.; removed = 0.
        for start in range(0, len(p), chunk_size):
            block = p[start:start+chunk_size]
            u = block @ self.inputs
            ends = np.empty_like(u)
            for j in range(len(z)):
                ends[:, j], _ = lfilter([beta[j]], [1., -decay[j]], u[:, j], zi=[decay[j]*z[j]])
            begins = np.vstack((z, ends[:-1]))
            change = np.expm1(-x)*begins+beta*u
            integrated = beta*begins+delta*u
            supplied = block @ self.source_sums*dt
            storage_change = change @ self.storage
            loss = integrated @ self.loss
            block_storage = change @ self.body_storage
            block_balance = block @ self.body_inputs*dt-block_storage-integrated @ self.body_flow
            max_error = max(max_error, float(abs(supplied-storage_change-loss).max()))
            max_block_error = max(max_block_error, float(abs(block_balance).max()))
            removed += float(loss.sum())
            end = start+len(block)
            y[start:end] = ends @ self.sensors.T
            body_rate[start:end] = block_storage/dt
            loss_rate[start:end] = loss/dt
            mean_rate[start:end] = (change @ self.sensors.T).mean(axis=1)/dt
            z = ends[-1].copy()
        supplied = float((p @ self.source_sums).sum()*dt)
        storage_change = float((z-initial_z) @ self.storage)
        error = supplied-storage_change-removed
        ledger = dict(input_energy_j=supplied, stored_energy_change_j=storage_change,
                      removed_heat_j=removed, energy_error_j=error,
                      normalized_energy_error=abs(error)/max(1., abs(supplied)),
                      max_interval_energy_error_j=max_error, max_body_interval_error_j=max_block_error,
                      numerical_heat_balance_screen=bool(abs(error)/max(1., abs(supplied)) < 1e-7 and max_error < 1e-7 and max_block_error < 1e-7),
                      reduced_order=len(rates), physical_model_qualified=False)
        return y, ledger, dict(body_storage_rate_w=body_rate, boundary_loss_w=loss_rate,
                               sensor_mean_rate_k_per_s=mean_rate)


def project(g, c, b, h, loss, groups, bank, shifts, tolerance=1e-11):
    c = np.asarray(c)
    mandatory = body_basis(c, groups)
    snapshots = np.column_stack([bank['instantaneous']]+[bank[s] for s in shifts])
    snapshots *= np.sqrt(c)[:, None]
    for _ in range(2):
        snapshots -= mandatory @ (mandatory.T @ snapshots)
    norms = np.linalg.norm(snapshots, axis=0)
    snapshots = snapshots[:, norms > 1e-20]/norms[norms > 1e-20]
    if snapshots.shape[1]:
        q, r, _ = qr(snapshots, mode='economic', pivoting=True)
        diagonal = abs(np.diag(r))
        rank = int(np.count_nonzero(diagonal > tolerance*diagonal.max()))
        q = q[:, :rank]
        # Reproject after QR to suppress contamination by dependent snapshots.
        for _ in range(2):
            q -= mandatory @ (mandatory.T @ q)
        q, _ = qr(q, mode='economic')
        basis = np.column_stack((mandatory, q))
    else:
        basis = mandatory
    orthogonality = float(abs(basis.T @ basis-np.eye(basis.shape[1])).max())
    if orthogonality > 1e-9:
        raise ValueError('reduction basis failed orthogonality')
    v = basis/np.sqrt(c)[:, None]
    gv = g @ v
    cr = v.T @ (c[:, None]*v)
    gr = v.T @ gv
    asymmetry = float(abs(gr-gr.T).max()/max(1., np.linalg.norm(gr, np.inf)))
    if asymmetry > 1e-10:
        raise ValueError('projection conductance lost symmetry')
    rates, eigenvectors = eigh((gr+gr.T)/2, (cr+cr.T)/2)
    if rates.min() <= 0:
        raise ValueError('reduced model is not stable')
    w = v @ eigenvectors
    inputs = np.asarray(b.T @ w)
    sensors = np.asarray(h @ w)
    storage = w.T @ c
    removed = w.T @ loss
    body_storage = np.column_stack([(w[np.asarray(ids).ravel()]*c[np.asarray(ids).ravel(), None]).sum(axis=0) for ids in groups])
    # G w is constructed from the original sparse operator, not the reduced
    # equations, to audit independent physical body fluxes.
    gw = g @ w
    body_flow = np.column_stack([gw[np.asarray(ids).ravel()].sum(axis=0) for ids in groups])
    body_inputs = np.column_stack([np.asarray(b[np.asarray(ids).ravel()].sum(axis=0)).ravel() for ids in groups])
    source_sums = np.asarray(b.sum(axis=0)).ravel()
    constant_reconstruction = float(abs(w @ storage-1.).max())
    if constant_reconstruction > 1e-7:
        raise ValueError('constant-temperature field not preserved')
    body_dynamic_error = float(abs(body_flow-rates[:, None]*body_storage).max())
    body_input_error = float(abs(inputs @ body_storage-body_inputs).max())
    steady_reconstruction = w @ (inputs.T/rates[:, None])
    steady_error = steady_reconstruction-bank[0.]
    dc_state_error = float(abs(steady_error).max())
    dc_weighted_relative_error = float(np.max(np.linalg.norm(np.sqrt(c)[:, None]*steady_error, axis=0) /
        np.linalg.norm(np.sqrt(c)[:, None]*bank[0.], axis=0)))
    audit = dict(full_nodes=len(c), reduced_order=len(rates), shifts_per_s=list(shifts),
                 orthogonality_error=orthogonality, projected_relative_asymmetry=asymmetry,
                 constant_field_error=constant_reconstruction,
                 body_dynamic_identity_error=body_dynamic_error, body_input_identity_error=body_input_error,
                 dc_full_state_max_error_k_per_w=dc_state_error,
                 dc_capacity_norm_relative_error=dc_weighted_relative_error,
                 slowest_time_constant_s=float(1/rates.min()), fastest_time_constant_s=float(1/rates.max()),
                 physical_model_qualified=False)
    return Reduced(rates, inputs, sensors, storage, removed, body_storage, body_flow,
                   body_inputs, np.array([c[np.asarray(ids).ravel()].sum() for ids in groups]), source_sums, audit, w)


def frequency_reference(g, c, b, h, frequencies):
    source = b.toarray() if hasattr(b, 'toarray') else np.asarray(b)
    return {omega:np.asarray(h @ splu((g+1j*omega*diags(c)).tocsc()).solve(source.astype(complex))) for omega in frequencies}


def backward_euler_pulse(g, c, b, h, powers, dt, groups=None, loss=None):
    baseline = np.full_like(powers, .2)
    state = splu(g.tocsc()).solve(b @ baseline)
    factor = splu((g+diags(c/dt)).tocsc())
    values, body_means, heat_loss = [], [], []
    removed = np.zeros(powers.shape[1])
    initial_energy = c @ state
    supplied = np.zeros(powers.shape[1])
    max_heat_error = 0.
    steps, stride = round(1/dt), round(.1/dt)
    for i in range(steps):
        p = powers if i < steps//2 else baseline
        state = factor.solve(b @ p+c[:, None]/dt*state)
        if groups is not None:
            removed += (loss @ state)*dt
            supplied += np.asarray(b @ p).sum(axis=0)*dt
            max_heat_error = max(max_heat_error, float(abs(supplied-(c @ state-initial_energy)-removed).max()))
        if (i+1)%stride == 0:
            values.append(np.asarray(h @ state))
            if groups is not None:
                body_means.append(np.array([c[np.asarray(ids).ravel()] @ state[np.asarray(ids).ravel()]/c[np.asarray(ids).ravel()].sum() for ids in groups]))
                heat_loss.append(removed.copy())
    if groups is None:
        return np.array(values)
    return dict(sensors=np.array(values), body_means=np.array(body_means), cumulative_boundary_heat_j=np.array(heat_loss),
                max_numerical_heat_balance_error_j=max_heat_error)
