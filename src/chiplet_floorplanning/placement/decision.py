"""Decide whether indistinguishable operating conditions can share a physical design."""

from dataclasses import dataclass

import numpy as np

from .problem import Layout
from .search import layout_key


def guaranteed_amplitude(mean_c, gain_k_per_w, ceiling_c, max_w):
    """Largest amplitude within [0,max_w] whose entire affine field is below a ceiling."""
    mean = np.asarray(mean_c, float)
    gain = np.asarray(gain_k_per_w, float)
    if mean.shape != gain.shape or not mean.size or (gain < 0).any() or max_w < 0:
        raise ValueError("expected matching field and nonnegative gain and amplitude")
    if mean.max() > ceiling_c:
        return None
    rising = gain > 0
    ratios = (ceiling_c - mean[rising]) / gain[rising]
    return float(ratios.min(initial=max_w))


def worst_regret_bounds(lower, upper):
    """Per-design bounds on worst regret across one group of scenarios.

    Rows are scenarios and columns are designs, all minimizing the same loss.
    Use +inf in both arrays for a design infeasible in that scenario. Each
    oracle may use any design feasible there. A fixed choice must be feasible
    in every row. Passing the same array twice gives the exact worst regret.
    """
    lower, upper = (np.asarray(a, dtype=float) for a in (lower, upper))
    if lower.ndim != 2 or lower.shape != upper.shape or not lower.size:
        raise ValueError("expected two matching nonempty scenario-by-design matrices")
    valid = np.isfinite(lower) & np.isfinite(upper) & (lower <= upper)
    absent = np.isposinf(lower) & np.isposinf(upper)
    if not (valid | absent).all() or not valid.any(axis=1).all():
        raise ValueError("each scenario needs a feasible design and ordered cost intervals")

    designs = lower.shape[1]
    lo = np.full(designs, np.inf)
    hi = lo.copy()
    for j in np.flatnonzero(valid.all(axis=0)):
        rivals = np.arange(designs) != j
        # A contender cannot incur regret relative to itself.
        best_other_upper = upper[:, rivals].min(axis=1, initial=np.inf)
        best_other_lower = lower[:, rivals].min(axis=1, initial=np.inf)
        lo[j] = max(0.0, float((lower[:, j] - best_other_upper).max()))
        hi[j] = max(0.0, float((upper[:, j] - best_other_lower).max()))
    return lo, hi


@dataclass
class ThermalCandidate:
    layout: Layout
    length_m: float
    peaks_c: np.ndarray
    die_peaks_c: np.ndarray


def search_thermal_targets(anchors, targets_c, propose, evaluate, budget, attempts_per_step=256):
    """Generate a shared layout using the worst excess over fixed scenario targets.

    propose(parent, die_peaks) returns a legal, budget-feasible layout or None.
    evaluate receives a fresh geometry and returns data for the visible scenarios.
    Each queried geometry costs one thermal evaluation per scenario. Spent trials
    are retained even when they do not replace the incumbent.
    """
    targets = np.asarray(targets_c, dtype=float)
    if targets.ndim != 1 or not targets.size or not anchors or budget < 0:
        raise ValueError("expected scenario targets, initial layouts and a nonnegative budget")

    def score(point):
        if point.peaks_c.shape != targets.shape or len(point.die_peaks_c) != len(targets):
            raise ValueError("candidate must use the same scenarios as the objective")
        excess = point.peaks_c - targets
        return float(excess.max()), float(excess.sum()), point.length_m

    current = min(anchors, key=score)
    initial = current
    visited = {layout_key(row.layout) for row in anchors}
    trials = []
    for _ in range(budget // len(targets)):
        worst = int(np.argmax(current.peaks_c - targets))
        for attempt in range(1, attempts_per_step + 1):
            layout = propose(current.layout, current.die_peaks_c[worst])
            if layout is not None and layout_key(layout) not in visited:
                break
        else:
            break
        visited.add(layout_key(layout))
        candidate = evaluate(layout)
        accepted = score(candidate) < score(current)
        trials.append((current, worst, attempt, candidate, accepted))
        if accepted:
            current = candidate
    return initial, current, trials
