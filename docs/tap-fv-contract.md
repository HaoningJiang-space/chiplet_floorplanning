# Frozen TAP finite-volume research model v1

Selected before new temperature comparisons on 2026-11-12, following Chat's
bounded Gate A at `5b43c4a`. Reuse the repository's existing `assemble_package`
finite-volume implementation; HiTS remains the numerical solver. Do not patch
native HotSpot or require agreement with its different discrete model.

## Equations and boundaries

Temperature unknowns are solid cell-centre temperature rises above 45 C.
Each face uses the sum of two material half-cell resistances; reciprocal face
conductances enter symmetric off-diagonal entries and both diagonal entries.
Top convection uses half the top-cell material thickness plus 1/h in series.
Bottom, lateral surfaces and uncovered horizontal ledges are adiabatic. Contact
resistance is zero. There is no radiation, temperature-dependent material,
leakage feedback, or transient capacitance in this steady experiment.

Use full resolved 100 x 100 x 1 mm copper spreader and 200 x 200 x 6.9 mm copper
sink centered on the sourced 50 mm interposer; k=400 W/(m K). Uniform top h is
2777.7778 W/(m2 K), preserving TAP's h=1/(0.1*0.06^2). There are no lumped
peripheral nodes or hidden boundary elimination. These are source case-study
parameters and explicit assumptions, not measurements of an Ascend product.

Retain all six TAP input layers: substrate .2 mm k=1/3.33; C4 .07 mm; TSV
interposer .11 mm; microbumps .01 mm; dies .15 mm; TIM .02 mm k=4. Retain TAP's
square area-fraction mixtures with Cu k=400, Si=100 and underfill=1.6, using
C4 diameter/pitch 250/600 um, TSV 10/50, bumps 25/45. Do not silently substitute
circular area fractions. No calibration of these effective properties is claimed.

Microbump material occupies each bump-expanded chip footprint; underfill fills
the rest. Silicon occupies the same expanded footprint in the die layer;
underfill fills its gaps. The original core alone receives its full sourced
power, uniformly by area. Thus ring geometry and total/core power are retained.

## Deliberate differences from source reproduction

- Resolve spreader/sink solids rather than using HotSpot's peripheral lumped
  package network. Actual matching temperatures are neither assumed nor required.
- Remove TAP's artificial 0.5 mm perimeter bump-material strips. Full-layer
  underfill outside chips is the declared model. This removes the source-only
  border restriction, not a physical routing keepout.
- Use boundary-conforming material/power rectangles rather than HotSpot's
  occupancy-threshold material assignment. No geometric snapping occurs.
- Use 64 nominal intervals across the 200 mm outer domain, subdividing at every
  material/core edge using the existing conformal mesh. This is a declared
  discretization, not a proven continuum error bound. Candidate rankings close
  to mesh sensitivity must later be marked unresolved.

The existing full independent source geometry domain is retained. This admission
case uses its already-published geometry witness, not a newly temperature-selected
layout. Source compatibility with the former HotSpot input generator is not
needed for this representation.

## Bounded admission evidence required

One uniform two-solid-layer analytic example checks cell locations, heat flux,
and half-cell external boundary distance. Changing top h must leave all internal
face coefficients unchanged. One complete Ascend 350 W case must pass source
mapping, heat balance, passivity and original-equation residual checks, and
HiTS/direct same-equation comparison. Numerical/model admission is not empirical
physical calibration or qualification of the finite routing benchmark.

All comparative layout methods must later share this contract and mesh policy.
No optimizer, thermal optimality claim, or routing feasibility follows from
passing these thermal checks. Freeze finite resources and exact candidate
subdomain before comparative layout experiments.
