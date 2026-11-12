# Legal-move connectivity and all-start ablation

The local audit independently enumerated all original Cartesian choices and
matched every saved legal ordinal, then built adjacency by legal state lookup.
It confirms Chat's structural observation without assuming it from the review.
No new temperature solves were required; all values use the existing oracle.

| Moves | Thermal-class edges | Thermal-class components | Original-state components |
| --- | ---: | --- | --- |
| Atomic: centre OR rotation | 135 | 68, 8, 1 | 4,352, 512, 64 |
| Joint: centre, rotation, or both | 206 | 77 | 4,928 |

Without restarts, class 0 cannot reach the global minimum with atomic moves.
Its component minimum is 76.54626 C, versus 76.19670 C globally: a conditional
reachable-optimum gap of 0.34957 K. Joint moves remove that disconnection.
This is a proved property of this finite graph, not geometric infeasibility,
a lower bound for algorithms with restarts, or a proof about the full centre
grid. The original implementation already allowed joint moves. The earlier
plan's wording was ambiguous; its saved results remain unchanged.

## All 77 starts, same query budget

The predeclared [audit protocol](tap-search-structure-plan.md) uses all starting
classes, one fixed seed per start, three budgets and five method/move variants:
1,155 complete replays. Restarts can cross disconnected components and remain
enabled for both local methods under identical rules. The table shows budget 32.

| Policy | Optimum hits / 77 | Median gap (K) | Worst gap (K) | Mean proposals | Mean cache hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Random | 31 | 0.1470 | 0.2748 | 31.0 | 0 |
| Atomic descent | 17 | 0.2658 | 0.5581 | 223.1 | 192.1 |
| Joint descent | 47 | 0 | 0.4139 | 191.4 | 160.4 |
| Atomic SA | 13 | 0.3496 | 0.5057 | 104.4 | 73.4 |
| Joint SA | 35 | 0.1497 | 0.4213 | 61.3 | 30.3 |

Joint moves improve the recorded aggregate hit counts for both local policies,
but this is not a statistically established or universal advantage. Changed
neighbourhoods also change proposal probabilities and restart behavior; the
ablation does not isolate connectivity as the sole cause. Random retains the
best worst gap at every budget and the best median gap at budgets 8 and 16.
At budget 32 joint SA's median is also slightly worse than random. Do not claim
a consistently superior optimizer or treat joint moves as novel.

Queries plus cache hits equal proposals plus one (the initial evaluation).
This is explicit offline accounting, not an online runtime benchmark. Strong
same-model floorplanning baselines and multiple large-domain workloads remain
required before a method claim.

## Numerical Pareto reporting

Transitive integer objective bins use 1e-6 K and 1e-9 mm steps. They produce
eight non-dominated bins and preserve all contributing original records.
Classes 0 and 76 now share a bin instead of treating a 3.93e-11 K difference
as a meaningful improvement. This is a reporting convention, not an additional
physical-equivalence theorem; values close across a bin boundary may still
remain separate. The legacy raw-float list is preserved as historical evidence.

The [complete audit](evidence/tap-search-structure.json) includes component
members, full-state counts, all 1,155 query traces and all budget summaries.
Regression checks reproduce all 360 historical query traces and best values
exactly, and test atomic disconnection, bin membership and cost accounting.
All 285 current-workspace tests and the documented two-chiplet CLI passed
(including three still-uncommitted local-access tests).

## Next decision

Use atomic/joint distinctions, complete cost accounting and an explicit tie
policy in the online evaluator. Retain the three thermal-sensitivity regimes
from the prior diagnostic. Before running a large pilot, freeze representations,
common starts, budgets and Pareto metrics with Chat review. A B*-tree compacted
layout and an arbitrary centre-grid layout do not automatically share the same
feasible set; that compatibility needs an explicit design, not a baseline label.
