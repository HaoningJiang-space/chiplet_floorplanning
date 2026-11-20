"""Choose a joint landing by checking only candidates that can still beat the incumbent."""

from dataclasses import dataclass

import numpy as np


def hot_cells(initial_k, count, spacing_cells):
    """Pick the hottest remaining cell outside the previous observers' exclusion disks."""
    remaining = initial_k.copy()
    y, x = np.ogrid[:remaining.shape[0], :remaining.shape[1]]
    for _ in range(count):
        cell = np.unravel_index(remaining.argmax(), remaining.shape)
        if not np.isfinite(remaining[cell]):
            break
        yield tuple(int(v) for v in cell)
        remaining[(y-cell[0])**2 + (x-cell[1])**2 < spacing_cells**2] = -np.inf


@dataclass
class SearchResult:
    best: int
    best_gain_k: float
    checked: list
    observers_added: list


def search_observers(initial_upper_k, costs, verify, observation=None, *, tighten=None):
    """Optimize over a finite bank, including staying put at index zero.

    verify(i) returns (exact worst-boundary gain, boundary and cell attaining it).
    observation(witness) returns the old peak minus the candidate temperature at
    that fixed cell, for every candidate. Each value is an upper bound on gain.
    An optional more expensive candidate-specific upper bound is requested at
    most once, before a contender reaches its first whole-field verification.
    """
    upper = np.asarray(initial_upper_k, dtype=float).copy()
    pending = set(range(1, len(upper)))
    best, gain = 0, 0.
    checked, added = [], []
    tightened = set()
    while pending:
        candidate = min(pending, key=lambda i: (-upper[i], costs[i], i))
        if upper[candidate] < gain - 1e-8:
            break
        if tighten is not None and candidate not in tightened:
            upper[candidate] = min(upper[candidate], tighten(candidate))
            tightened.add(candidate)
            continue
        pending.remove(candidate)
        actual, witness = verify(candidate)
        if actual > upper[candidate] + 1e-8:
            raise ValueError("observed gain exceeded the bound")
        checked.append(candidate)
        if (-actual, costs[candidate], candidate) < (-gain, costs[best], best):
            best, gain = candidate, actual
        if observation is None or upper[candidate] <= actual + 1e-8:
            continue
        if not any(upper[i] >= gain - 1e-8 for i in pending):
            break
        values = observation(witness)
        if abs(values[candidate] - actual) > 1e-8:
            raise ValueError("new observer did not reproduce the candidate's worst peak")
        upper = np.minimum(upper, values)
        added.append(witness)
    return SearchResult(best, gain, checked, added)
