"""Decide whether indistinguishable operating conditions can share a physical design."""

import numpy as np


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
