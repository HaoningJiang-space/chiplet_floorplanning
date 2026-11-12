"""Decision sensitivity under explicitly supplied, deterministic error bounds.

An observed model discrepancy is not automatically an error bound. These
functions do not estimate bounds or certify the evidence supplied by callers.
"""
import math


def _bound(value, evidence):
    if value is None:
        if evidence is not None:
            raise ValueError('bound evidence without a bound')
        return None
    if not math.isfinite(value) or value < 0 or not isinstance(evidence, str) or not evidence.strip():
        raise ValueError('finite nonnegative bound and explicit evidence required')
    return float(value)


def compare_temperature_difference(delta_k, *, difference_bound_k=None, evidence=None):
    """delta = T(A)-T(B); bound must apply to this paired difference directly.

    A common temperature offset can cancel. Do not silently add marginal errors
    or assume their independence/correlation to construct this input bound.
    """
    if not math.isfinite(delta_k):
        raise ValueError('finite paired temperature difference required')
    bound = _bound(difference_bound_k, evidence)
    interval = None if bound is None else [delta_k-bound, delta_k+bound]
    status = 'uncertainty_unquantified'
    if interval is not None:
        status = ('a_cooler_under_supplied_bound' if interval[1] < 0 else
                  'b_cooler_under_supplied_bound' if interval[0] > 0 else
                  'indistinguishable_within_uncertainty')
    return dict(delta_a_minus_b_k=delta_k, difference_interval_k=interval,
                status=status, bound_evidence=evidence, physical_certification=False)


def assess_timing_margin(setup_ns, hold_ns, *, slack_bound_ns=None, evidence=None):
    """Bound covers the error of EVERY setup/hold slack, not one cell delay.

    A uniform bound applies to min(slack) because minimum is 1-Lipschitz in the
    infinity norm. Shared-clock cancellation must be handled before supplying
    a bound; marginal cell discrepancies cannot establish it automatically.
    """
    if not all(math.isfinite(v) for v in (setup_ns, hold_ns)):
        raise ValueError('finite setup and hold observations required')
    bound = _bound(slack_bound_ns, evidence)
    margin = min(setup_ns, hold_ns)
    interval = None if bound is None else [margin-bound, margin+bound]
    status = 'uncertainty_unquantified'
    if interval is not None:
        status = ('feasible_under_supplied_bound' if interval[0] >= 0 else
                  'infeasible_under_supplied_bound' if interval[1] < 0 else
                  'indistinguishable_within_uncertainty')
    return dict(nominal_feasible=margin >= 0, minimum_slack_ns=margin,
                distance_to_zero_ns=abs(margin), minimum_slack_interval_ns=interval,
                status=status, bound_evidence=evidence, physical_certification=False)
