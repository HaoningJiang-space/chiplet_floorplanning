# Predeclared validation plan: package thermal and PDK timing

Recorded before the new integration experiments. Do not change a failing
threshold after inspecting an outcome without preserving the original verdict.

## Scope

Validate numerical package equations against independently assembled MFIT
networks, electrical RC propagation against ngspice, and cross-die setup/hold
using actual SKY130 and GF180 Liberty data. These checks do not establish
measured package accuracy or qualification of a high-speed D2D PHY. Core-cell
links are an explicit test boundary; pad/ESD/channel qualification is separate.

## Thermal expectations

- Geometry, thickness, conductivity, convection, heat-source locations and node
  ordering must match before a solver comparison. Interfaces use the series
  half-cell resistances. Void gaps have no artificial lateral conduction.
- Both original and reference networks must conserve injected power. Relative
  energy error <= 1e-8 (absolute floor 1e-10 W); residual <= 1e-8 W for small cases.
- Same-grid MFIT comparison: max node temperature difference <= 1e-7 K. This is
  an equation/assembly comparison, not experimental material calibration.
- Zero power gives ambient. Doubling power doubles temperature rise for fixed
  linear properties. Uniform single-column conduction matches series R by
  <= 1e-8 K. Increasing a positive convection coefficient must not raise the
  maximum temperature for unchanged nonnegative heat sources.
- Report at least three mesh levels and peak change; require the last peak
  change <= 0.25 K for this demonstration. Retain any nonconvergence.

## Electrical expectations

- Pin all source revisions and library hashes; verify voltage, temperature,
  units, sequential arcs and slew conventions. Keep data/clock package nets
  separate and inspect both parasitic annotations and expanded clock paths.
- Use one launched bit and a forwarded clock; capture on the opposite edge to
  make the initial sampling relation explicit. STA is required to produce
  both max/setup and min/hold paths. A reported violation is a valid observation,
  not an analysis failure and not something to hide with false paths.
- At fixed capacitance, increased data resistance should delay data, reduce
  setup margin and improve hold margin. Increased clock resistance should
  delay capture, improve setup and reduce hold (check actual rise/fall limits).
- Changing only clock period must change setup by half the period change for
  the specified opposite-edge relation. Check arithmetic to 1e-5 ns.
- Validate the distributed passive RC network with ngspice against an
  independent state-space solution for the same imposed waveform: 50% crossing
  error <= 1% or 1 ps, whichever is larger; report 20–80% slew as well.
  This validates the channel model, not transistor-level driver equivalence.
- Negative controls: missing Liberty, wrong cell/endpoint, missing parasitics,
  and malformed model must fail explicitly. No missing timing becomes zero slack.

## Evidence and reporting

Archive raw generated netlists, SPEF, Tcl, SPICE, reference inputs, stdout and
reports under ignored `results/`. Commit reproducible generators, source/hash
lock, tests and compact receipts. Report physical assumptions and numerical
checks independently. Add no fitted factors merely to obtain passing results.
