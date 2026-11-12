# R3 physical comparison metrics

Primary question: **under the same interconnect budget, how much cooler is the
best layout found by each algorithm?** Thermal-query allowance (64 including
16 shared initial states) controls computational effort; it is distinct from
the physical interconnect budget. A higher legal-proposal rate alone does not
answer the placement-quality question.

For method A's evaluated legal layouts S_A and a shared span ceiling B:

`T_A(B) = min { T_max(x) : x in S_A and L(x) <= B }`.

Against baseline R, `delta_T(B) = T_R(B) - T_A(B)` in K; positive means cooler.
The reverse comparison uses `L_A(C) = min { L(x) : x in S_A and T_max(x) <= C }`
and reports `100 * (L_R(C) - L_A(C)) / L_R(C)` percent, when the denominator is
positive. These are best *attained* values, not proofs of global optimality.

Current L is `sum(d_ij * Manhattan(centre_i, centre_j)) / sum(d_ij)` in mm,
including the same directed demand entries as the original implementation.
It is a demand-weighted mean centre distance, not total routed wirelength,
propagation delay, or package routing capacity. Temperature is the existing
peak power-layer temperature. Power, package, cooling, geometry and demand
remain fixed within each workload.

The thresholds come from the **earlier 20-layout sensitivity sample**, using
nearest-rank p25/p50/p75 independently for span and temperature (sorted indices
4/9/14). Use p50 for the primary table; retain all three anchors. They are common
to every method and seed within a workload, never fitted to a candidate's final
results. They are research anchors, not sourced product limits. Their use on
the completed v4 pilot is explicitly retrospective; they are frozen before new
R3 comparisons. If product constraints become available, declare a new contract.

Selection uses raw inclusive `<=`, then minimizes the other objective, the
constraint objective, and query index in that order. Select from all actual
evaluated points, not only a rounded Pareto archive. Do not interpolate or join
the minimum temperature of one layout to the minimum distance of another.
Each selection retains query index, temperature AND span. If none qualifies,
report `not_attained`, not global infeasibility, infinity, zero gain, or an
invented penalty. Paired gains are null unless both methods attain the same
constraint; separately count candidate-only, baseline-only and neither cases.

| Role | Metric | Direction / interpretation |
| --- | --- | --- |
| Primary quality | Attained T_max at the shared L budget; paired delta_T in K | Lower absolute temperature / positive reduction |
| Reverse tradeoff | Attained L at the shared T_max ceiling; paired reduction in mm and percent | Lower distance / positive reduction |
| Quality progress | The same constrained metrics at 16/32/64 queries and actual endpoint | Initialization is charged; retain capped endpoints |
| Auxiliary Pareto quality | HV, paired delta_HV and HV gain from initialization | Higher; same frozen scales, not a physical benefit |
| Auxiliary marginal extrema | Separately best temperature/span and gains | May belong to different layouts; never a joint benefit |
| Feasibility effort | Legal/illegal proposal fractions, plus search-only legal fraction | Search-only excludes initialization; all internal TAP attempts count |
| Diversity | Unique full legal layouts, distinct thermal states, unique-layout fraction, archive objective-bin count | Descriptive exploration measures, not substitutes for quality |
| Reuse | Cache hits and cache fraction among legal evaluations | Reuse count, not an inferred speedup |
| Cost | Thermal queries, proposals, geometry and solve seconds, total seconds | Include initialization and failed attempts |
| Conditional mutation cost | Candidate checks and filter seconds | Included in total seconds, not free repair |
| Outcome | Complete / capped / unknown, actual attained query count | Keep all trials; no successful-survivor-only comparison |

`tools/tap_r3_metrics.py` computes schema `tap-research-metrics-v2` in both policy
entry points: `physical_comparison`, `anytime_physical_comparison`, `auxiliary`
and `effort`. Callers supply a frozen comparison contract; an old low-level call
without one emits no physical comparison rather than inventing budgets.
`paired_difference` now requires the shared contract and no longer exposes an
unqualified marginal `temperature_gain_k`. `report_tap_physical.py` aligns case,
seed and the actual 16 initial joint points, then computes each paired difference
before summarizing. Original search selection/acceptance is unchanged: this is
a correction of comparison criteria, not a silent change of the baseline policy.

The original TAP cases retain v4 normalization and reference (1.2, 1.2).
Report each workload separately. HV is dimensionless and must not be presented
as a percentage temperature or wirelength improvement. Objective bins remain
1e-6 K / 1e-9 mm; HV tie tolerance remains 1e-10. A pooled empirical front is
not a global optimum. Larger pin-level cases will need their own predeclared
scales and rotated pin-to-pin distance metric; do not reuse centre-span scores
as if they measured actual routes.

Report the individual paired physical differences, conditional median/range,
attainment counts and win/tie/loss, alongside actual selected joint points and
cost. Numeric aggregation is conditional on both methods attaining the ceiling;
never hide failed attainment or incomplete runs with survivor-only averages.
Primary temperature ties use 1e-6 K as a reporting convention, not significance
or measured physical resolution. No significance claim follows from three seeds.

## TAP policy component completed alongside metric integration

`run_tap_policy` now provides a single-chain TAP-derived coordinate policy with
the upstream default `adpTWv2`: zero thermal weight below 80 C; otherwise
`a=min(0.1+0.01*(max(Told,Tnew)-45),0.9)`, distance weight `1-a`.
Observed ranges are updated before acceptance, including all 16 initial states.
When either range vanishes, both objective differences use the upstream raw
fallback. The chain starts at shared first-fit, with all 16 evaluations in its
archive. It keeps the 90% close / 10% jump proposal component.

The declared budget adaptation is a geometric cooling schedule from 1 to 0.01:
before a proposal, `tau=0.01**((queries-16)/max(1,budget-17))`. Thus a 64-query
trial starts at 1 and reaches 0.01 before its last fresh query. Cache hits hold
the schedule but consume proposals; the common 10,000-attempt cap bounds them.
The original stage-length/decay schedule and B*-tree initializer are replaced
by this schedule and the shared initialization. This is a source-derived
adaptation, not exact reproduction of the upstream HotSpot/CPLEX pipeline.
It can intentionally prefer distance in the weak-temperature Ascend case;
the source's 80 C rule is not retuned to manufacture a thermal improvement.

The [R3 protocol](tap-r3-protocol.md) supplies the updated manifest, all five
policy choices, new-method batch runner and physical report. The old v4 manifest,
thermal evidence and historical report remain unchanged and labeled historical.
