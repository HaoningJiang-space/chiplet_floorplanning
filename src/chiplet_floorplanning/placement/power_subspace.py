"""Certify finite-pool peaks using few independent power differences on a fixed passive network."""
import numpy as np


def subspace_peaks(start_w, pool_w, start_rise_k, source_response, response_cap):
    """Return all peak rises and a common numerical margin, using at most response_cap RHS.

    source_response(d) returns rises on the active power layer for signed slot sources d.
    It uses the same fixed linear heat network as start_rise_k. Positive slot powers
    and nonnegative thermal transfer bound the effect of power reconstruction error.
    """
    delta = (pool_w-start_w).T
    basis, singular, right = np.linalg.svd(delta, full_matrices=False)
    rank = int(np.sum(singular > singular[0]*max(delta.shape)*np.finfo(float).eps))
    if rank > response_cap:
        raise ValueError(f'pool requires {rank} responses, cap is {response_cap}')
    if np.any(start_w <= 0):
        raise ValueError('a positive reference power per slot is needed for the error bound')
    coeff = singular[:rank, None]*right[:rank]
    residual_w = delta-basis[:, :rank] @ coeff
    relative = np.max(np.abs(residual_w)/start_w[:, None])
    guard = float(relative*start_rise_k.max()+1e-8)
    if rank:
        response = np.stack([source_response(direction) for direction in basis[:, :rank].T], axis=1)
    else:
        response = np.empty((len(start_rise_k), 0))
    # A box in source coordinates encloses every allocation. A node whose highest
    # possible temperature stays below another node's floor cannot be the peak.
    pos, neg = np.maximum(response, 0), np.minimum(response, 0)
    lo, hi = coeff.min(axis=1), coeff.max(axis=1)
    lower = start_rise_k+pos@lo+neg@hi
    upper = start_rise_k+pos@hi+neg@lo
    possible = upper+guard >= lower.max()-guard
    peaks = np.max(start_rise_k[possible,None]+response[possible]@coeff, axis=0)
    return peaks, dict(rank=rank, equivalent_peak_guard_k=guard, relative_power_residual=float(relative),
                       active_nodes=len(start_rise_k), kept_nodes=int(possible.sum()))
