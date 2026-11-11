# Geometry and low-speed source-synchronous interface closure

The user selected the low-speed source-synchronous prototype. Work remains on
`main`. Physical measurements are unavailable; this gate addresses declared
model geometry, interface connectivity and electrical checks, not fabrication
or high-speed PHY signoff.

## Geometry gates

- Preserve exact legal rectangular die coordinates and quarter-turn rotations;
  construct a geometry-conforming finite-volume mesh without snapping dies.
- Conserve every power block's watts, material footprint area and shared-face
  heat flow. Support nonuniform cell widths, anisotropic conductivity and
  explicit interface contact resistance with units.
- Preserve existing aligned-case results. Validate analytic series resistance,
  zero power, positivity, symmetry, translation/rotation, arbitrary sub-grid
  movement and convergence of instance temperatures and setup/hold.
- Sample a continuous reconstruction inside each die only; never interpolate
  through an insulating void. Keep aligned uniform meshes as a documented
  regression control. Temperature-node locations remain explicit.
- Numerical gates: relative energy error <= 1e-8, independent analytic
  temperature error <= 1e-7 K, final mesh change at sampled locations <= 0.1 K
  and setup/hold <= 1 ps on the declared examples. These are numerical gates,
  not measurement-accuracy claims.

## Interface gates

- Keep the original SKY130 TX / GF180 RX failure. Inspect its actual selected
  timing arcs, pad capacitance ownership and slew definitions before choosing
  a feasible interface configuration. Never relax library limits to pass.
- Require explicit pad mode, core/I/O voltage domains, clock edge relationship,
  complete data/clock parasitics, library provenance and electrical checks.
- A positive case must have actual pad paths and in-domain transitions/loads.
  A failing case returns a structured rejection and retains diagnostic logs.
- Support different electrical roles for the two public PDKs if their original
  forward direction cannot satisfy the published constraints. State any such
  design change explicitly and keep the original negative case reproducible.
- Compare independently computed timing-table values and channel responses.
  Transistor-level pad waveform validation requires usable device/netlist
  models; absence or incompleteness must be reported, never replaced by a
  synthetic waveform presented as PDK validation.

Run required unit/CLI checks and prior regressions before publishing. Retain
new negative results and every change in a physical assumption.
