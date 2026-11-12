# Revised acceptance: uncertainty in the decision

The user's revised acceptance supersedes any interpretation that all external
models must agree to a universal absolute tolerance before layout research can
continue. Exact geometry, connections, edge semantics, units, resource accounting
and conservation remain strict. Numerical convergence, model discrepancy and
input-contract mismatch are distinct. Neither a 0.02 K mesh threshold nor a
near-zero SPICE/Liberty difference is a universal physical admission rule.

The immediate goal is floorplanning with explicit model scope and uncertainty.
Stop refining already adequate solver consistency. Prioritize paired layout
temperature differences and setup/hold margins that could change the decision.
Existing historical screen results remain recorded without retroactively
changing their thresholds or claiming that they prove a tool defect.

`uncertainty.py` now provides two deterministic, conditional decisions:

- For a paired temperature difference, use a bound on that difference, with
  explicit evidence. An interval spanning zero returns
  `indistinguishable_within_uncertainty`; a separated interval establishes an
  ordering only under the supplied bound.
- For timing, use a uniform bound covering **every complete setup/hold slack**.
  The minimum slack then lies in `[minimum-bound, minimum+bound]`. Nonnegative
  lower limit establishes conditional feasibility; a negative upper limit
  establishes conditional infeasibility; otherwise the decision is unresolved.

Missing bounds return `uncertainty_unquantified`, not zero uncertainty and not
an equivalence claim. The decision summary now reports this state and the
distance of minimum setup/hold slack from zero for every analyzed candidate.
That distance is a sensitivity threshold, not an estimated error or confidence
interval. Shared-clock cancellation belongs in a future bound derivation.
Observed isolated-cell discrepancies do not automatically bound full-path error.

The existing finite-model zero-cost proof is retained. Physical ordering remains
unquantified: paired xy mesh changes are observations, not bounds covering
materials, z discretization, package boundary, Pad or channel uncertainty.
No new statistically justified error bound has been obtained in this stage.

Next prioritize a matched-output thermal-backend comparison (including HiTS if
its model permits), and decision sensitivity under explicitly declared model
alternatives. Do not claim real-hardware robustness from an arbitrary margin
or from another paper's reported error. The user's pasted literature values
have not been independently audited here and are not adopted as thresholds.
