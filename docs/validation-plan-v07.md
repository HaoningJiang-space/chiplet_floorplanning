# v0.7 routing counterfactual and constraint-necessity gate

Keep the v0.5 27 placements, powers, thermal stack, TT25 GPIO libraries and
20 ns demonstration period fixed. Do not tune frequency or objective weights
to create a timing bottleneck. Do not enable the failed v0.6 hot-pad model.

## Geometric contract before timing

Use one planar interposer signal layer with the existing 10 um trace width,
10 um minimum edge spacing and 10 um package-edge clearance. These spacing
values are declared experiment assumptions, not foundry rules. Explicit
rectangle keepouts are supported; the reference has none. Silicon die
footprints are not automatically metal keepouts: routing below the die is
permitted on this interposer layer. No vias or free second signal layer.
Finite-width traces and square joins/endcaps must remain within the package,
avoid declared keepouts and each other, and have no self overlap/backtracking.
Geometric feasibility under this contract is not bump escape, package DRC,
electromagnetic qualification or physical signoff. Keep missing models explicit.

- R1: shortest paths on a rectilinear visibility grid, routing both net orders
  and retaining the shortest legal pair found. Each second path avoids the
  first route; both avoid other-net terminals. This is not a proof of globally
  shortest two-net routing. Record Manhattan lower bounds separately.
- R2: reproduce original data y=1.5 / clock y=4.5 mm corridors, including
  their geometric audit and electrical rejections.
- R3: exactly swap the two corridors; reject intersections instead of silently
  inserting an unmodeled bridge/via or permitting a short.
- R4: enumerate R1 and the fixed Cartesian portfolio data y={1.5,2.5,3.5},
  clock y={2.5,3.5,4.5} mm, including R2/R3 as controls. First require geometry,
  electrical, setup and hold legality; among feasible routes minimize total
  wirelength. Also report achievable margin range separately. No reward for
  surplus slack in the constrained thermal objective. This finite portfolio
  is not an exhaustive routing optimizer.

## Numerical and causal reporting

Reuse a thermal result only across routes of the identical placement/power/
stack/mesh, since wire heat and metal-dependent conductivity are absent from
this model. Rebuild the thermal mesh/matrix for every different placement.
Use 48x32 and 96x64 requested conformal meshes as before. Require final peak
change <=0.1 K and heat-balance error <=3e-8 W. Instrument mesh/input construction,
power mapping, matrix assembly, thermal solve, SPEF generation and STA execution.
Performance samples are diagnostic wall times, not a speedup benchmark.

Report per-policy and common-accepted-cohort pair counts; the pairs share one
design and are not independent experimental replicates. Keep the prior 2e-6 ns
printed-slack tie tolerance. Also report an explicitly separate 1 ps effect-size
filter; it is not a physical error bound. Compute Pareto sets and the actual
constrained thermal optimum. Select the thermal baseline from the geometrically
routable, electrically legal pool **before** filtering setup/hold, then ask
whether it is timing-feasible. Do not infer necessity from weighted winners.

Maintain S_T and the temperature-mediated pair interaction I(A,B) as missing
until a consistent same-interface temperature model passes its gate. Never use
zero to mean unmeasured. The core-only FF model cannot fill this field.

## Timing-critical benchmark admission

Review public protocol/implementation requirements and pin cited source files.
A testbench clock, an unrelated ASIC's core Fmax, an aggregate link throughput,
or a borrowed PDK timing target is not an admitted constraint for this GPIO lane.
Admission requires a traceable clock/duty/edge contract, actual mapped endpoint
design and pad/load/PVT coverage. If no reviewed candidate satisfies these
requirements, record the missing dependencies and leave the benchmark gate open.
The current 20 ns assumption is a control, not proof of real timing pressure.

Keep source and meaningful failure tests separate from raw reports/PDKs. Run
the full unit suite, original two-chiplet CLI, new routing experiment and
affected old prototype/ranking regressions before committing/pushing main.
