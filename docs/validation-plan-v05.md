# v0.5 open-case validation and layout ranking gate

Scope: maintain only `main`; fix the independent-die sidewall defect before
publishing new results. Numerical/model checks are not hardware certification.
No physical measurement data are available. Do not merge the FF core-only
thermal profile with the TT GPIO lane into a claimed physical hot-link model.

## Required cases and source policy

- MFIT original homogeneous and heterogeneous package/power examples: preserve
  dimensions, offset layer footprints, material anisotropy, boundary conditions
  and mean declared power trace. Refine XY; no claim of transient equivalence.
- RapidChiplet original 16-chiplet example: retain placement, dimensions, power
  and PHY endpoint locations; validate conversion against upstream geometry
  calculations. Thermal package parameters are additional declared assumptions.
  Architectural links do not become synchronous timing paths automatically.
- PULP serial_link physical-layer RTL: pin upstream and dependency revisions,
  run self-checking SDR transport cases with source clock and asynchronous local
  RX clock, including idle and bounded backpressure. This is RTL functional
  evidence, not PDK-mapped STA or metastability proof.
- OpenSTA upstream golden cases: reproduce SDF, Liberty min/max and SPEF
  annotation results; identify these as engine regressions, not independent
  chiplet designs or physical validation.

Download upstream artifacts under ignored `local/`, pin hashes, keep source
licenses/provenance, and do not copy source models into this repository.

## Thermal corrections

- Preserve per-cell die ownership in chiplet-only layers. Distinct die sidewalls
  are adiabatic by default even at zero geometric gap. Shared package layers
  still conduct normally. An explicit sidewall contact resistance enables a
  declared conductive interface; never infer fused silicon from adjacency.
- Support per-die conductivity on a common layer stack and offset rectangular
  layer footprints needed by MFIT. Do not claim arbitrary per-die thickness,
  topography, rotated material tensors or general 3D CAD.
- Test touching, small-gap and ordinary-gap dies, explicit contact and distinct
  material conductivities against independent small-network calculations.

## Predeclared numerical gates

- Power mapping and energy balance: relative error <= 1e-8.
- Matched MFIT networks: pointwise difference <= 1e-7 K with explicitly matched
  discretization and physics; original differing meshes are reported separately.
- OpenSTA upstream golden numerical rows: <= 1e-6 at printed precision; reject
  missing paths or tool errors. No golden file regenerated from our output.
- RTL checks: exact received words/order/count, bounded completion and expected
  negative-control failures; simulated channel delay is explicitly idealized.
- Open thermal cases: final peak/block-mean change <= 0.1 K, otherwise report
  not converged and refine within resource limits. Do not retune thresholds.

## Ranking experiment

Fixed two-die design, powers, package, TT pad models and 20 ns period. Evaluate
27 geometry-legal candidates from TX x={0.5,1.5,2.5} mm, RX x={6,7,8} mm,
TX y={1,2,3} mm; RX y=2 mm; all dimensions/orientations unchanged. Data and
clock routes use separate fixed horizontal corridors at y=1.5 and 4.5 mm.
These are declared ideal routing policies, not a DRC-clean automatic router.

Separately sweep data-only and clock-only detours on a fixed layout to identify
skew effects and electrical limits. Preserve rejected and timing-failing cases.
Compare thermal rank, worst setup/hold margin rank and a declared normalized
joint score (temperature rise / 10 K minus margin / 1 ns, equal weights).
Report sensitivity to thermal weight 0.25, 0.5, 0.75; do not tune weights to
manufacture a conflict. Report all pairwise numerical reversals and ties.

Re-evaluate layouts on finer meshes and report uncertainty intervals. Physical
model error is unknown without calibration; a ranking separation exceeding
numerical error alone does not establish a physical or publishable advantage.
No optimizer or SA is introduced before this gate is assessed.
