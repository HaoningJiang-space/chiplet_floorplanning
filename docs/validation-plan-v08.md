# v0.8 E1: source contributions before further optimization

Keep v0.7 (`a51c3d4`) as a negative baseline. This stage answers E1 only: how
fixed-layout source contributions, absolute placement and cooling assumptions
explain the existing thermal ordering. E2/E3 stay gated on sourced physical
resources and an admitted interface timing requirement.

## Frozen experiment

Use all 27 original placements and the same 2 W TX / 1 W RX block distributions,
rotations, material footprints and package dimensions. Use the original 48x32
and 96x64 requested conformal grids. At each layout solve total power, TX-only
and RX-only power, preserving **both** dies, every layer and all boundaries.
Compare assembled conductance matrices, sinks and material-node identities
exactly when only power changes. Independently solve each RHS; do not recover
one contribution by subtracting it from the total.

Sum temperature **rises**, not absolute temperatures. Require pointwise
superposition error <=1e-8 K over all material nodes, linear residual <=1e-8 W,
heat-balance error <=3e-8 W and nominal final peak-grid change <=0.1 K. Report
each source at the total-field hotspot and at each die's total-field hotspot.
Do not add independently located source peaks. A source's hotspot contribution
divided by its power is a pattern-weighted transfer coefficient in K/W, not a
universal scalar die thermal resistance.

Report rigid translations 00/12/24 and relative RX movement 10/13/16. At every
layout record the passive material structure; moving the unpowered die can
change G and hence the heated die's own contribution. Self-source change is
not automatically a pure side-boundary effect.

## Boundary sensitivity controls

Use a fixed declared six-profile set, not tuned for rank reversal:

| Profile | Top h (W/m²K) | Bottom h (W/m²K) | TIM k (W/mK) |
| --- | ---: | ---: | ---: |
| nominal | 1000 | 0 | 10 |
| weaker_top | 500 | 0 | 10 |
| stronger_top | 2000 | 0 | 10 |
| bottom_only | 0 | 1000 | 10 |
| lower_tim_k | 1000 | 0 | 1 |
| higher_tim_k | 1000 | 0 | 20 |

These are sensitivity assumptions around the existing demonstration, not
measured cooling/TIM distributions. Keep thickness and all other material
parameters unchanged. Report every grid change even if it exceeds 0.1 K;
do not automatically accept a new profile at nominal resolution.

On nominal layout 00, rotate the entire die/power arrangement 180 degrees about
the package center. The homogeneous package and boundary contract must preserve
peak temperature and source hotspot contributions (<=1e-8 K). This is a symmetry
check; it does not assert finite-domain translation invariance.

## Attribution and reporting

Recompute balanced 3x3x3 main and interaction sums of squares for peak
temperature and source contributions. Require exact factorial coverage and
orthogonal sum-of-squares closure within floating-point tolerance. This is a
descriptive decomposition of deterministic cases, without p-values or causal
percentages. No independent-replicate claim is made.

Keep E1 distinct from timing, physical calibration and link-power feedback.
Archive compact evidence and a reproducible scientific figure. Run unit tests,
the original two-chiplet CLI and this experiment before commit/push on main.

## Refinement amendment after initial execution

The initial bottom-only profile reached 0.101544 K peak change from 48x32 to
96x64, exceeding 0.1 K. Preserve that observation and add 192x128 for **all 27**
bottom-only placements. Judge its final step against the unchanged 0.1 K gate;
report both steps. Also require every boundary profile to meet the final-step
gate. No cooling/material value or objective is changed based on the result.
The first run also exposed a report-script rotation attribute typo after the
thermal solves; correct it and rerun the full experiment before publishing.
