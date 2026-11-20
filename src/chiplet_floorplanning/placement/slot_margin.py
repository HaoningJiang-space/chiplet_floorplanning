"""Minimize peak temperature over two power classes on identical occupied slots."""

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp


def choose_hot_slots(response, low_w, high_w, count, *, time_limit_s=2.):
    """A thermal peak lower bound and a trial assignment, before the wire cap.

    Rows are observed cells, columns are physical slots (K/W). A hot slot
    adds high_w-low_w to its baseline of low_w. Full-board peaks dominate
    observed peaks. An unconstrained wire relaxation includes every legal permutation.
    """
    response = np.asarray(response, float)
    if response.ndim != 2 or min(response.shape) == 0:
        raise ValueError("expected at least one observed cell and one occupied slot")
    n = response.shape[1]
    if not 0 <= count <= n or not 0 <= low_w <= high_w:
        raise ValueError("invalid hot-slot count or ordered power levels")
    base = low_w * response.sum(axis=1)
    delta = (high_w-low_w) * response
    if count in (0, n) or high_w == low_w:
        hot = np.arange(count)
        peak = float(np.max(base + delta[:, hot].sum(axis=1)))
        return hot, dict(weighted_k=peak, conditional_k=peak, milp_lower_k=None,
                         lower_k=peak - 1e-7, mip_completed=False)
    rows = np.column_stack((delta, -np.ones(len(response))))
    number = np.r_[np.ones(n), 0.]
    objective = np.r_[np.zeros(n), 1.]
    bounds = [(0., 1.)]*n + [(None,None)]
    lp = linprog(objective, A_ub=rows, b_ub=-base, A_eq=number[None,:], b_eq=[count],
                 bounds=bounds, method="highs")
    if not lp.success:
        raise RuntimeError(lp.message)
    # Any nonnegative normalized weights certify a bound: the weighted
    # temperature cannot exceed the highest temperature. Minimize its value
    # by placing the extra watts on the count lowest weighted responses.
    weights = np.maximum(0., -lp.ineqlin.marginals)
    weights /= weights.sum()
    by_slot = weights @ delta
    weighted_bound = float(weights @ base + np.sort(by_slot)[:count].sum())

    # If slot j runs hot, it must carry its own extra power. Minimize the
    # contribution of the other count-1 hot slots at each observer. At least
    # count slots must be hot, so the count-th lowest conditional peak is necessary.
    conditional = []
    for j in range(n):
        rest = np.delete(delta, j, axis=1)
        cheapest = np.sort(rest, axis=1)[:,:count-1].sum(axis=1)
        conditional.append(float(np.max(base + delta[:,j] + cheapest)))
    hot_bound = float(np.sort(conditional)[count-1])

    opt = milp(objective, integrality=np.r_[np.ones(n),0],
               bounds=Bounds(np.r_[np.zeros(n),-np.inf],np.r_[np.ones(n),np.inf]),
               constraints=[LinearConstraint(number,count,count), LinearConstraint(rows,-np.inf,-base)],
               options={"time_limit":time_limit_s,"mip_rel_gap":0.})
    if opt.status not in (0,1):
        raise RuntimeError(opt.message)
    z = lp.x[:n] if opt.x is None else opt.x[:n]
    hot = np.argsort(-z,kind="stable")[:count]
    dual = getattr(opt,"mip_dual_bound",None)
    dual = float(dual) if dual is not None and np.isfinite(dual) else None
    bound = max(weighted_bound,hot_bound,dual if dual is not None else -np.inf)
    return np.sort(hot), dict(weighted_k=weighted_bound, conditional_k=hot_bound,
        milp_lower_k=dual, lower_k=bound-1e-7, mip_completed=bool(opt.success))
