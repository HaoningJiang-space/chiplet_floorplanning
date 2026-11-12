# Return to floorplanning: bounded validation and research gates

User-directed scope, 2026-11-11. Starting remote `main` was
`aa8fdd926e39bde165b90435008e1fce9c338750`; fetch succeeded.

The existing finite 12-layout experiment has zero incremental timing
temperature cost under its four assumed profiles. This is a conditional negative
result, not evidence for a new joint optimization algorithm. Physical model
precision is supporting infrastructure, not the primary research contribution.

## 1. Finish the current fabric experiment, then freeze its scope

Use the existing rot180, rot90 and rot270 layouts, saved supplies, workload,
clock and routing. No arbitrary clock tightening or resource reduction.

- Finish the already launched global/local uniform 25 C and 65 C controls on
  the complete fabric. These keep RC fixed and test temperature propagation
  together with export-order sensitivity. The predeclared 0.5 ps screen is a
  numerical diagnostic, not a physical error bound.
- Obtain complete, admitted logs for the cold/hot comparisons of these three
  layouts at the existing two time steps. Preserve historical suppressed logs
  and failed runs; do not retrospectively qualify them.
- Compare all three layout pairs on the same lane/edge and separately on
  minimum setup and hold available windows. Report
  `I_T(A,B) = [W_hot(B)-W_hot(A)] - [W_cold(B)-W_cold(A)]`.
  Report both cold/hot ordering and any reversal. Available windows are not
  characterized setup/hold slack.
- Tabulate step sensitivity, uniform-control discrepancy and STA-versus-SPICE
  model discrepancy separately. Their empirical extrema are not confidence
  intervals or guaranteed physical bounds. If an ordering difference is small
  relative to observed sensitivity, label it unresolved. Keep package, material,
  real PHY/Pad and boundary uncertainty explicitly unquantified where applicable.

Exit with a finite three-layout decision report, including negative results and
unresolved comparisons. Stop expanding isolated-cell validation. Reopen a model
only for a demonstrated decision-relevant defect or a new benchmark requirement.
This stage does not certify a real package.

Exit is not admission. Keep `execution_complete`, `numerical_control_passed`
and `physical_qualified` separate. A failed uniform screen makes the thermal
interpretation unresolved; retain the measurements rather than tune the screen.
For each comparison report ordering as `stable`, `changed`, or `unresolved`
within the tested numerical/model variants. Separately report whether the
interaction is resolved: a nonzero interaction need not reverse an ordering.
These are layout-plus-routing comparisons, not isolated rotation effects.
None of these labels establishes a physical error bound or physical signoff.

The uniform-control runner is `tools/audit_xyce_uniform.py`. With the existing
local artifact trees, run it once per temperature (25 or 65), using a fresh
output directory:

```powershell
python tools/audit_xyce_uniform.py `
  results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness `
  results/physical-calibration/xyce-fabric-rot180-reviewed `
  results/physical-calibration/integrated-transistors-v1 `
  --temperature 65 --output results/physical-calibration/xyce-uniform65-v1
```

At publication of this contract, both temperature jobs are still running locally;
no uniform-control result is claimed. The runner retains incomplete receipts and
uses the strict diagnostic inventory with the increased warning limit. Local
validation: 232 unit tests passed; the documented two-chiplet CLI returned 3 W
and 34.1886 C, explicitly uncalibrated with timing not run.

## 2. Build a sourced and scalable floorplanning benchmark

Before selecting numerical values, maintain a provenance ledger for chiplet
dimensions, workload power, PHY/bump locations and escape rules, timing or
bandwidth requirements, package routing resources and cooling boundaries. Each
entry must distinguish published measurement/specification from derived value
and explicit assumption. Do not combine unrelated products into a purportedly
validated physical system.

Expand independent positions and rotations, communication topology and port
distribution. Preserve common physical assumptions across methods. Deliver
small exactly checkable domains and larger domains using the same rules.
Feasible certificates must bind geometry, routing and evaluator inputs;
search exhaustion or timeout alone is not an infeasibility certificate.
Before launching benchmark experiments, freeze the initial small exact domain
and larger case family, topology, independent position/rotation domains,
resource rules, evaluator and deterministic generation recipe. Source collection
does not itself count as a benchmark result, and must not become an unbounded
replacement for the fabric validation phase.

## 3. Establish structure before proposing an optimizer

Investigate two hypotheses, not yet established findings:

1. Routing cut/escape capacity provides necessary conditions for feasibility;
   a violated capacity bound is a sufficient infeasibility certificate
   under a precisely defined routing graph and demand model. An unviolated cut
   is not a proof of feasibility. Count actual
   resource consumption; path-search failure is not a capacity proof.
2. For a fixed linear thermal operator and boundary conditions, transfer
   responses can support reusable thermal evaluation or certified bounds.
   Placement-dependent material/operator changes invalidate naive reuse and
   must be bounded or recomputed.

Check any proposed bound against exhaustive small domains, including negative
controls. Publish one or two useful, falsifiable structural results before
designing a new search method. These hypotheses may fail; do not claim novelty
without reviewing relevant primary literature.

## 4. Algorithm gate and review cadence

Only proceed if the benchmark exhibits a meaningful method gap. Compare mature
placement/floorplanning/routing baselines with identical physical constraints,
candidate domains and budgets. Require ablations and held-out workloads.
If timing does not affect selection, retain it as validation/constraint and
study thermal-aware floorplanning under finite interconnect resources.

Experiments remain local. Publish coherent validated milestones promptly on
`main` with `[skip ci]`, verify remote HEAD, then ask Chat mode to independently
read that SHA and its Git history through the connected GitHub account. Record
which findings were checked and which remain open. An earlier Chat review does
not automatically approve subsequent commits or reproduce local experiments.

## Chat review receipt

Chat mode independently read `ea6e9308e61e1837c1d6bb136af93d018dedc6ed`
and its parent through connected GitHub, confirming the one-commit, three-file
change. Its completed review accepted this bounded direction, requested the
three admission states, explicit comparison verdicts and a frozen benchmark
scope, and corrected the cut-condition wording. These requested changes are
being implemented locally; the review did not rerun local tests or simulations.
Conversation: https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865

On 2026-11-12 the recovered Chat review explicitly covered the two commits
after ea6e9308 through `ba4fbebec05745374b20ec0b126f18fcfc9dc1c0`.
It accepted the independent execution/numerical/physical states, uniform-control
evidence, strict cold/hot diagnostic admission and pinned source-ledger boundary.
It independently read the upstream GitHub configurations, but did not execute
local tests or raw simulations and did not inspect the DATE paper PDF. It kept
physical benchmark construction and solver-status separation as open gates.
Later ordering/structure commits are not covered by that review. The three-layout
report will receive a separate review after publication; it remains pending here.
Recovered conversation: https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447
