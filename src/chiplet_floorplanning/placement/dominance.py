"""Compare spatial peak temperatures over the steady mixture of two power maps."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PeakCurve:
    """Continuous piecewise-linear peak; weight is the fraction of the second map."""

    weights: np.ndarray
    temperatures: np.ndarray

    def at(self, weights):
        return np.interp(weights, self.weights, self.temperatures)


def peak_curve(first, second):
    """Form the upper envelope of cell temperatures from the two endpoint fields.

    Both inputs must describe the same cells on one layout, in the same units.
    Matching NaNs denote cells outside the observed layer.
    """
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if first.shape != second.shape or not np.array_equal(np.isnan(first), np.isnan(second)):
        raise ValueError("endpoint fields must have the same spatial support")
    inside = ~np.isnan(first)
    intercept = first[inside]
    slope = second[inside] - intercept
    if not len(slope) or not (np.isfinite(slope).all() and np.isfinite(intercept).all()):
        raise ValueError("expected finite temperatures at the observed cells")

    # Increasing slopes give the order in which lines can take over the peak.
    # At equal slope only the largest intercept can contribute.
    lines, starts = [], []
    for cell in np.lexsort((-intercept, slope)):
        if lines and slope[cell] == slope[lines[-1]]:
            continue
        start = -np.inf
        while lines:
            last = lines[-1]
            start = (intercept[last] - intercept[cell]) / (slope[cell] - slope[last])
            if start > starts[-1]:
                break
            lines.pop()
            starts.pop()
        starts.append(start if lines else -np.inf)
        lines.append(cell)

    weights = np.array([0., *(w for w in starts if 0 < w < 1), 1.])
    active = np.asarray(lines)[np.searchsorted(starts, weights, side="right") - 1]
    return PeakCurve(weights, intercept[active] + weights * slope[active])


def worst_excess(candidate, baseline):
    """Maximum signed excess and one attaining weight, measured against baseline."""
    excess = candidate.at(baseline.weights) - baseline.temperatures
    index = int(np.argmax(excess))
    return float(excess[index]), float(baseline.weights[index])


def potential_hotspots(temperatures):
    """Retain cell rows that can matter at a nonnegative mixture of the mode columns."""
    rows = np.asarray(temperatures, dtype=float)
    if rows.ndim != 2 or not all(rows.shape) or not np.isfinite(rows).all():
        raise ValueError("expected a finite cell-by-mode matrix")
    kept = []
    for cell in np.argsort(-rows.sum(axis=1), kind="stable"):
        if not kept or not (rows[kept] >= rows[cell]).all(axis=1).any():
            kept.append(cell)
    return rows[kept]


def simplex_worst_excess(candidate, baseline):
    """Maximum signed peak difference on the simplex of steady power mixtures.

    Rows are cell temperatures, columns the same ordered workloads on both layouts.
    Matrices may be prefiltered with potential_hotspots for repeated comparisons.
    """
    from scipy.optimize import linprog

    a, b = np.asarray(candidate, dtype=float), np.asarray(baseline, dtype=float)
    if (a.ndim != 2 or b.ndim != 2 or not all(a.shape) or not all(b.shape)
            or a.shape[1] != b.shape[1] or not np.isfinite(a).all() or not np.isfinite(b).all()):
        raise ValueError("expected finite cell temperatures for the same modes")
    modes = a.shape[1]
    weights_sum = np.array([[*np.ones(modes), 0.]])
    objective = np.r_[np.zeros(modes), -1.]
    bounds = [(0, 1)] * modes + [(None, None)]
    best, mixture = -np.inf, None
    for cell in a:
        # The signed excess of this cell must be no larger than its difference
        # from *each* baseline cell. Maximize that common lower bound.
        inequalities = np.column_stack((b - cell, np.ones(len(b))))
        lp = linprog(objective, A_ub=inequalities, b_ub=np.zeros(len(b)),
                     A_eq=weights_sum, b_eq=[1.], bounds=bounds, method="highs")
        if not lp.success:
            raise RuntimeError(f"thermal mixture optimization failed: {lp.message}")
        if -lp.fun > best:
            best, mixture = -float(lp.fun), lp.x[:-1]
    return best, mixture
