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

## 3. Establish structure before proposing an optimizer

Investigate two hypotheses, not yet established findings:

1. Routing cut/escape capacity provides necessary infeasibility certificates
   under a precisely defined routing graph and demand model. Count actual
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
