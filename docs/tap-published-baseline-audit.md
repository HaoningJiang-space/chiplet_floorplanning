# Published TAP baseline: initialization is not the optimizer

Read-only source audit at upstream commit
`3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb`, while the unchanged v4 pilot runs.
Repository freshness was checked successfully at local/remote `cdf97f2`.
No upstream optimizer or new thermal experiment was executed for this audit.

## Two distinct stages in the actual implementation

The [entry point](https://github.com/bu-icsg/TAP-2.5D/blob/3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb/sim_annealing.py)
performs coordinate-space thermal/wirelength simulated annealing. It chooses
a close one-grid-step move with probability 0.9 and a jumping placement with
probability 0.1. The latter selects one chiplet, random centre coordinates and
an optional quarter turn; it retries geometry and eventually falls back to a
close move. It evaluates HotSpot and the CPLEX routing objective, updates
observed objective ranges, and uses the configured weighting rule. Its annealing
temperature starts at 1, stops below 0.01 and decays after `intp_size` steps.
This is not the four-chain fixed-normalization SA in our pilot.

The [initializer](https://github.com/bu-icsg/TAP-2.5D/blob/3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb/init_placement.py)
separately calls B*-tree fast SA, relaxes coordinates to the placement grid,
and converts lower-left coordinates into centres. The
[fast SA code](https://github.com/bu-icsg/TAP-2.5D/blob/3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb/fastSA.py)
optimizes wirelength and package edge extent, not temperature.
Therefore, describing the whole published TAP optimizer as a compact B*-tree
search would be incorrect. The representation warning in our Chat guidance
applies to a native tree search; it does not rule out adapting TAP's subsequent
coordinate-space optimizer to the common evaluator.

## Consequences for the next comparison

After the fixed pilot and R2 review, the most direct published-method candidate
is this two-stage TAP pipeline. Keep two questions separate:

1. Under shared initialization, common geometry, thermal evaluation and
   centre-span objective, does its close/jump proposal and annealing policy
   perform differently? Label this a TAP-derived adaptation, not reproduction
   of the paper's HotSpot/CPLEX result. Explicitly declare changed normalization,
   termination, failed-proposal handling and any bug fixes.
2. Does its B*-tree/fast-SA initialization help under the same downstream
   optimizer? Charge initialization computation and evaluations; do not grant
   it an optimized starting point for free or silently project shared layouts
   into another representation. This is an initialization ablation.

The common-evaluator adaptation must translate centres and inflated bump
footprints correctly, retain the full geometry checker, count every candidate
attempt including internal retries, and preserve solver failures as unknown.
Original dynamic normalization and adaptive weighting are method components;
replacing them with our frozen scales is a declared variant, not an invisible
implementation detail. A finite-budget schedule must be specified before new
comparative runs. No settings are chosen from the partial pilot results.

One concrete upstream edge path needs a regression before reuse:
`jumping_neighbor` normally returns four values but its exhausted-retry fallback
returns the three-value `close_neighbor` result, while its caller unpacks four.
Do not execute the upstream entry point blindly (it also contains shell cleanup
commands). Audit and adapt isolated policy functions instead.

This is a source-backed next-stage candidate, not an implemented baseline,
performance result, exhaustive current SOTA survey, or completion of the goal's
published-method comparison requirement. The current 45-run pilot remains a
mechanism comparison and continues without modification.
