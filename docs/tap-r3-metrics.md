# R3 metrics fixed before comparative runs

Primary question: does conditional legal mutation improve Pareto placement
quality under the same thermal-query budget? A higher legal-proposal rate alone
does not answer it.

| Role | Metric | Direction / interpretation |
| --- | --- | --- |
| Primary quality | Final hypervolume (HV), paired delta against baseline | Higher; same workload, seed, initialization, query budget and frozen scales |
| Quality progress | HV at 16/32/64 queries; final HV minus initial-16 HV | Higher; initialization is charged |
| Absolute quality | Best peak temperature (C), best centre span (mm) | Lower; these two minima may belong to different layouts |
| Absolute gains | Initial best minus final best, in K and mm | Positive is improvement; report paired gains as well |
| Feasibility effort | Legal/illegal proposal fractions, plus search-only legal fraction | Search-only excludes initialization; all internal TAP attempts count |
| Diversity | Unique full legal layouts, distinct thermal states, unique-layout fraction, archive objective-bin count | Descriptive exploration measures, not substitutes for quality |
| Reuse | Cache hits and cache fraction among legal evaluations | Reuse count, not an inferred speedup |
| Cost | Thermal queries, proposals, geometry and solve seconds, total seconds | Include initialization and failed attempts |
| Conditional mutation cost | Candidate checks and filter seconds | Included in total seconds, not free repair |
| Outcome | Complete / capped / unknown, actual attained query count | Keep all trials; no successful-survivor-only comparison |

`tools/tap_r3_metrics.py` computes the common `research_metrics` field emitted
by both policy entry points. `paired_difference` computes one candidate-minus-
baseline HV difference; the caller must align workload/seed/scales/initialization.
For temperature and span it reports baseline-minus-candidate so positive gains
favor the candidate. Elapsed change is candidate-minus-baseline.

The original TAP cases retain v4 normalization and reference (1.2, 1.2).
Report each workload separately. HV is dimensionless and must not be presented
as a percentage temperature or wirelength improvement. Objective bins remain
1e-6 K / 1e-9 mm; HV tie tolerance remains 1e-10. A pooled empirical front is
not a global optimum. Larger pin-level cases will need their own predeclared
scales and rotated pin-to-pin distance metric; do not reuse centre-span scores
as if they measured actual routes.

Report the three individual paired differences, their median/range and
win/tie/loss counts, with absolute-objective Pareto plots and cost. Do not tune
scales after seeing the winner. Negative or quality-neutral results remain
valid. No significance claim is made from three paired seeds.

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

Tests exercise adaptive acceptance, its degenerate-range branch, charged
proposal/failure paths, complete 64-query execution and metric consistency on
synthetic objectives. No new thermal comparison has been launched yet; a new
source-bound R3 manifest/runner is still needed before that batch.
