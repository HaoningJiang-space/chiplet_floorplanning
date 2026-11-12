# Research evidence gates

The user's ten-metric goal is active. Success means defensible physical and
optimization evidence, not a desired ranking, a test count, or a promise of SOTA.
All runs stay local. Fetch GitHub at each new research session and before
publication. The user now explicitly requests timely pushes: preserve coherent
tested commits on main and push them, using [skip ci] to keep computation local.
Verify remote HEAD after each push. Earlier no-push records describe past policy.

| # | Metric | Current evidence and remaining gate |
|---|---|---|
| 1 | Geometry legality | Rectangle/rotation/overlap checks exist. Additional bump escape and realistic package design-rule domains must accompany new interfaces. Legality is always relative to declared rules. |
| 2 | Power conservation | Area mapping and reciprocal thermal network audits exist; new TTC geometry preserves each input across two heaters. Add link/PHY power with explicit ownership before claiming whole-system power. |
| 3 | Thermal accuracy | Independent numerical comparisons and 26 public TTC transients exist. The original source-geometry FV experiment fails improvement and mesh gates. A new coupled-refinement study closes the declared steady uniform-boundary numerical screen (~0.020 K vs continuum); see `ttc-numerical-closure-results.md`. This does not qualify the coarse transient model. Logger timing, nonuniform package boundaries and physical calibration remain unresolved. |
| 4 | Routing feasibility | Planar prototype plus finite-width two-layer discrete resources, unique multicast-clock trees, full-cut infeasibility certificates and independent tiny-graph exhaustive controls. See `shared-routing-results.md`. Greedy failure remains unknown. Real bump escape, foundry/package rule provenance, return paths and general physical routing remain open. |
| 5 | Electrical accuracy | Real-library Pad provenance, primitive measured IV and ideal passive channel controls. Full extracted Pad, stimulus/reference planes and measured package-channel calibration remain open. IV agreement is not waveform validation. |
| 6 | Timing correctness | Single-lane real-library checks plus complete synthetic shared-clock paths at 2/4/8/16 chiplets, early/late bounds, fanout and explicit common-root correlation. See `multilane-timing-results.md`. Actual complete interfaces, operating modes and PVT/electrical domain remain open. Negative-slack cases test correct rejection; they are not failures of the analyzer. |
| 7 | Multi-lane scale | Numerical integration now connects 120 data lanes and one shared routed clock to finite track capacity, unique SPEF R/C, independent RC first moments and complete STA paths (1,824 routed path checks). This remains a synthetic fixture, not a hardware benchmark or completed goal: actual package rules, Pad/channel characterization and thermal coupling are still open. |
| 8 | Thermal–timing coupling | Core-cell prototype only. Need the same physically characterized Pad/interface across temperatures, matching process, voltage, reference plane and local temperature map. No mixed-PDK or cross-corner surrogate coupling. |
| 9 | Joint optimization necessity | Existing conditional 50 MHz example gives zero temperature penalty for timing constraints. Preserve this negative result. Establish a supported regime where timing changes the thermal optimum beyond model and numerical uncertainty. |
| 10 | Optimization quality/generalization | Not established. Freeze benchmarks and evaluator first; equal-budget comparisons, multiple seeds, infeasible-case accounting, small-case enumeration and independent cases. A result may fail to exceed an existing method. |

## Governing scientific question

For a fixed physical interface, package, workload and admissible routing resource
set, when does timing exclude the thermally best placement by a resolvable margin?

Let `F` be the geometrically/routing-legal placement set, and `F_timing` its subset
passing complete timing and electrical requirements. For minimization of peak
temperature, `DeltaT = min(F_timing) T - min(F) T >= 0`, provided both feasible
sets are nonempty and the same thermal evaluator is used. An empty timing-feasible
set is reported as infeasible, not as a finite temperature penalty. Search failure
does not establish an empty feasible set. Approximate algorithms can violate this
inequality numerically; small-case enumeration separates search error from physics.

The decisive experiment changes one physical mechanism at a time: differential
data/clock delay, shared-clock routing competition, localized Pad temperature,
or boundary/contact uncertainty. Shared data/clock delay can cancel in setup;
wirelength alone is not the timing mechanism. An observed preference reversal
must survive the evaluator's supported uncertainty range. Model discrepancies
cannot be converted into invented probabilistic confidence intervals.

## Immediate sequence after the TTC observation audit

1. Preserve the source-selected end observation result, raw errors, original
   failed/bound-limited fits and all cases. Quantify common temperature bias
   versus spatial differential residual without choosing new parameters.
   The completed end-fit diagnostic places about 89–91% of held-out MSE in
   the common residual component. This is a decomposition, not attribution:
   boundary, ambient, initialization and sensor offset effects can overlap.
   Audit ambient provenance and boundary dynamics alongside spatial geometry.
2. Build a source-geometry thermal validation fixture: two heaters per sensor,
   active/bulk silicon, contact pad and explicit sink boundary. Establish power
   mapping, local storage/conduction and mesh/time convergence before fitting.
   Source-fitted material properties stay labeled fitted, not independent truth.
   This fixture now exists. Its frozen 3,361-node grid fails refinement and
   differs from the independent continuum by about 1.7 K on nominal controls.
   The steady gap is now reduced to about 0.020 K by coupled xy/z refinement,
   with no material changes. The new separable solver is restricted to uniform
   layers/boundary; transient convergence remains open.
3. Use fixed total power with distinct spatial excitations to test whether the
   geometry model predicts sensor differences better. Compare old and spatial
   models on identical cases, observation operator and fitting freedom. Hold
   logger phase/averaging unknowns explicit. The present holdouts are reused,
   so a later independent dataset or fixture is needed for blind generalization.
   The first 26-run spatial experiment failed; a converged steady continuum also
   failed to improve the secondary sensor-difference contrast. Compare uniform
   versus explicit copper base/fin boundaries next, keeping source parameters
   and diagnostic windows fixed and avoiding a unique causal claim.
   The full conforming package network now exists; its three completed
   refinement levels (0/1/2) have not passed boundary-effect convergence. New measured
   common-temperature slopes and a slow-mode lower bound expose the need for
   copper storage/fin heat-loss transient checks before physical attribution;
   see `ttc-package-boundary-results.md`. Finer local grids are still running.
   The new package transient reduction initially failed; numerical enrichment
   now passes the frozen same-grid controls on all four level-0 combinations
   without changing physical parameters. Large package storage and nearly
   settled spatial contrast coexist in the measured diagnostic windows within
   this coarse model. Level-1 transient and level-3 steady computations remain
   active; see `ttc-package-transient-results.md`. This does not close spatial
   convergence, initialization/measurement uncertainty or physical validation.
4. Develop multi-lane routing/timing bookkeeping in parallel only as a declared
   engineering model; do not promote it to physically qualified optimization
   until electrical and thermal domains close. Preserve routing failures.
5. Freeze a comparison protocol before algorithm selection: thermal-first,
   timing-first, alternating and joint search, same legal sets and evaluation
   budget, identical seeds/case sets, numerical uncertainty and wall time.
   Select current published baselines from their primary papers and runnable
   source at that stage; no current SOTA claim follows from this audit.

ChatGPT review is advisory: send concrete assumptions/results, record applied
methodological corrections, and independently verify factual claims in sources.
Its approval does not close any physical evidence gate.
Per the user's latest direction, request a comprehensive review of the full
relevant Git history only after completing a coherent major goal/stage. Keep
local commits timely while advancing; do not review each small code change.
