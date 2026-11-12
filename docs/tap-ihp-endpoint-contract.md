# TAP-derived IHP attachment geometry variant v1

Frozen before generating layouts or evaluating any temperature. This is a
redesigned mechanism family, not a manufactured TAP system, AIB, or an IHP PHY.
The earlier 45 um TAP domain and its zero aggregate-routing penalty stay intact.

Use the three original TAP core sizes, core powers and directed conductor
matrices. Select the pinned IHP/PacTech cupillar option 1 (35 um opening,
40 um opening spacing, nominal 75 um pitch, 44 um body, 7.5 um TopMetal2
enclosure). The source bundle is the one verified by the attachment audit.
No timing, throughput or voltage is inferred from conductor counts.

For each die, round the core bounding rectangle outward to a 75 um grid, centred
on the core. Add the smallest whole number of 75 um ring rows that can contain
all incident conductors on checkerboard-even sites. Grid cell centres are bump
centres; the full rectangle of grid cells is the expanded die envelope. Exclude
all cells of the rounded core rectangle. Checkerboard-odd ring sites are
reserved for PDN; unused even sites remain unpopulated. This 50% signal-site
policy is an explicit research assumption, fixed before search, not a sourced
PHY requirement or a proof of adequate PDN current/return capacity.

Allocate signal sites in ascending (row, column) order. Allocate incident
terminals by ascending (source die, destination die, wire index) from the
original demand matrix. Both ends of each conductor carry this identity, with
source/target roles. These are abstract conductor identities, not measured
product pin names. Do not merge bidirectional demand or invent clocks. An
actual source-synchronous PHY would need additional endpoint/clock allocation.

Each 50 um TopMetal2 landing fits inside its 75 um cell, including at die edges.
All ring centres lie on one integer lattice, so adjacent strips/corners cannot
introduce the close pairs possible with independently centred strips. Core
rounding, attachment ring and expanded dimensions are explicit outputs; the
original core dimensions and total heat are preserved. Four rotations act on
these fixed local coordinates. No die position or routing success selects a
pin map, ring size or PDN ratio.

Admission in this stage is only: integer coordinates, die/core containment,
non-overlapping landing discs, sourced opening separation, unique site and
terminal identities, exact two-ended conductor coverage, unchanged source
power, and the declared minimum ring-row count. It is not carrier DRC, escape,
track assignment, pad-to-PHY wiring, PI/SI, physical thermal calibration or full
package feasibility. Reserved PDN sites are not connected or qualified supplies.

Do not yet reuse the old placement witnesses, thermal classes or temperatures:
the die envelopes changed. Next freeze a new independently movable/rotatable
domain and a compatible layer/escape contract. Cooling, electrical loading and
power/return implementation must remain explicitly open until supplied. HiTS
continues to be used when the new thermal inputs are actually evaluated.
