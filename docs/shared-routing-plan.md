# Shared routing identity and finite conductor resources

Start from `f23cf17`, successful origin fetch at `c124aa9`. Keep ongoing package
calculations intact. This stage connects the shared-clock timing fixture to a
declared discrete routing fabric, without claiming real package design rules.

Each node is `(x, y, signal_layer)` on a uniform rectangular track grid. Edges
join adjacent nodes horizontally/vertically or by an adjacent-layer via. Trace
width, spacing, via landing diameter, layer separation and package margin are
explicit positive dimensions. Pitch must be at least the largest conductor/landing
diameter plus spacing. Package margins include half that diameter and edge
clearance. No different nets may occupy one node or edge; a single net can
branch at a shared node. This supplies finite-width clearance within this grid
model, not bump escape, foundry DRC, a reference plane or signal integrity.

Clock is one multi-sink net with one physical tree. Data lanes are distinct
point-to-point nets. Require terminal ownership, connectivity, acyclicity,
allowed resources and no dangling nonterminal leaves. Report unique wire/via
length and resource occupancy, alongside the larger sum of source-to-sink path
lengths; never charge that path sum as physical conductor length or capacitance.

Use a deterministic shortest-path tree grower with prior-net and other-terminal
reservations. Its failure means `search_failed`, never `infeasible`. A separately
checked x-section certificate enumerates every available edge crossing the
partition in every layer. Each distinct net with terminals on both sides needs
at least one crossing; a multicast clock is counted once. Demand greater than
capacity proves infeasibility only in the declared finite fabric.

An independent exhaustive tiny-graph reference enumerates all simple terminal
paths and unions into trees, then all nonconflicting assignments. Explicit
enumeration limits mean unknown if reached. Use it to check both feasible and
infeasible controls and preserve a feasible case where greedy ordering fails.

Frozen scalable fixtures: 2/4/8/16 chiplets, eight data lanes per receiver, one
multicast forwarded clock. Each receiver has nine track rows (eight data plus
clock). Two signal layers, 20 um pitch, 10 um trace/landing size and 10 um spacing;
these are synthetic rules. At the middle x-section, leave one crossing for
every data lane on layer 0 and one shared-clock crossing on layer 1. A paired
fixture removes the clock crossing. Its cut requires 8*receivers+1 independent
conductors but permits only 8*receivers. The source-side port row is not a real
chiplet footprint; placement and bump geometry are separate open gates.

Controls include a multicast tree with a single bottleneck and multiple sinks,
disconnected/dangling/cyclic routes, cross-net resource collisions, blocked
tracks, invalid dimensions, changed certificate partitions and mislabeled nets.
Validate the same data/clock identity used by the timing fixture. Shared routed
R/C and power ownership must use unique conductors; real channel coefficients
and return paths remain separate characterization prerequisites.
