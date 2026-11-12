# Move structure and numerical-tie protocol

Freeze this audit before evaluating the new ablation. Preserve the original
360-query experiment and its historical evidence. The old default neighbourhood
is joint: a single chip may change centre and orientation simultaneously.

Independently enumerate the 4,928 original legal states from the frozen choices
and exact geometry checks, and compare all saved legal ordinals. Build full
state graphs and 77-class graphs for atomic (centre OR orientation only) and
joint (either OR both) moves. Publish connected components and reachability of
the thermal optimum from class 0 without restarts. Do not equate disconnected
local moves with global infeasibility. A restart can cross components.

Use all 77 starting classes, seeds 20261112 + start index, budgets 8/16/32,
thermal-only objective, and the original descent/SA policies with identical
acceptance, normalization and restart rules. Compare atomic/joint variants and
one random control: 1,155 offline query-counted replays. Do not tune settings.
Report absolute thermal gaps, proposals, cache hits and restarts. This enumerates
starting classes, not all RNG outcomes, and gives no significance or SOTA claim.
Equal-query budget does not imply equal total runtime.

For numerical Pareto reporting, map temperature and span to integer bins by
rounding at 1e-6 K and 1e-9 mm, anchored at zero; retain all original records per
bin. Compute non-dominance in integer objective space. This gives a transitive
tie policy, unlike pairwise epsilon comparisons, but nearby values straddling
a bin boundary may remain distinct. The bins are a reporting convention, not
physical equivalence, accuracy or fabrication tolerance. Use 1e-6 K only as a
numerical hit tolerance. No new thermal solves are needed.

The large-domain baseline protocol remains a separate next step. In particular,
these two-anchor connectivity findings must not be assumed to hold on full
independent centre grids, nor called a novel move operator.
