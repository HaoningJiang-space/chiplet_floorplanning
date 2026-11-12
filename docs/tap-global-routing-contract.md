# Frozen TAP aggregate routing-resource model v1

This is a conditional global-routing mechanism model, not a complete physical
package or detailed-routing signoff. Freeze before evaluating the 4,928 layouts.
All algorithms use the same source demands and resources; no capacity sweep is
used to manufacture conflicts.

## Source and explicit assumptions

Retain TAP 3a3f4e5 complete six-chip Ascend dimensions, bump-expanded geometry,
45 um ring pitch and integer demand matrix. Treat each demand unit as an abstract
conductor to route, not a calibrated bit/s or UCIe channel. Unavailable PHY signal,
clock and return maps remain unavailable. The ring is assigned to the imported
abstract conductors; independent clocks and central power/return bump allocation
are not synthesized. Thus no claim of actual PHY or workload bandwidth closure.

Use the ICCAD 2018 interposer reference's 1 um width and 2 um pitch (Table 2,
https://people.bu.edu/joshi/files/interposer-nw-iccad-2018.pdf). A horizontal and a
vertical signal layer, continuous ideal reference planes, and no blocked metal
below chips are **model assumptions**, not an inferred TAP layer stack.
The assumed 1 um via landing with 1 um spacing shares the 2 um pitch; its actual
manufacturing rule and return-via allocation are not sourced.

## Finite graph

Tile the 50 mm interposer into 1 mm square bins (50 x 50), anchored at zero.
Each bin has a horizontal and a vertical node. Neighboring horizontal nodes
connect only along x; vertical nodes only along y. Each undirected track edge
has floor(1000/2)=500 conductor slots shared across directions and commodities.
An H/V edge inside each bin has floor(1000/2)^2=250,000 via-site slots, a geometric
upper bound for an ideal aggregate switchbox. There are no invented chip-gap
obstacles or artificial link-reach limits.

Explicitly generate the four nonoverlapping TAP ring rectangles. Tile each with
45 um square cells, using cell-centre bumps and floor-rounded lengths; rotate
these integer half-um coordinates with the die. Bin all bump sites. Each chip/bin
access gate has capacity equal to its number of bumps, shared across all incoming
and outgoing demands. Either routing layer may be accessed through that gate.
Only the source and destination chip's gates exist for a commodity; other chips
cannot be used as relays. This distributes access rather than concentrating a
whole side's pins into a single artificial point bottleneck.

This graph is a relaxation of detailed track/via assignment: counts do not prove
compatible track identities, same-layer spacing inside bins, pin escape geometry,
return continuity, channel SI/timing, or realizable via placement. A graph witness
is labeled as such. Failure of a sequential router is unknown, never infeasible.
A future cut certificate must be against the full original graph/demand, not a
residual graph left by earlier heuristic choices.

## Initial search and independent verification

Route directed commodities by decreasing demand, then source/sink IDs. For each,
use an integer maximum flow on the remaining shared resources with a super-source
cap equal to demand. Reserve positive directed flows against undirected resources.
No thermal value selects routing order or capacities. Retain the complete edge
flow witness for independent conservation, demand delivery, access direction,
allowed edge and aggregate capacity checks. Record failures as search unknown.

First evaluate the already-published full Ascend geometry witness. Only after
this graph implementation is validated, evaluate frozen-domain rotations and
thermal classes without assuming routing equivalence under half turns. A routing
success in this relaxation cannot close the original physical benchmark goal.

## Predeclared thermal-class cover experiment

After validating the original three witnesses and verifier negative controls,
check the frozen Ascend decision domain by thermal class. Decode the published
legal ordinals and regroup independently by the exact geometry/half-turn key.
For each class, try its legal states in ordinal order until one integer flow
passes independent replay; retain failed attempts as unknown. Stop after that
witness; do not adjust resources. No temperature value selects attempts.

If all classes have a witness, the aggregate graph's constrained and unconstrained
thermal minima are equal for every thermal objective constant within these
classes. This is an existential cover certificate, not a claim that every layout
is routable, nor a physical detailed-routing certificate. If any class is
uncovered, the zero-penalty proof is unresolved, not disproved. This experiment
needs no new thermal precision study and provides no justification for a new
optimizer when the penalty is zero.
