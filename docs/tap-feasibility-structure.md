# Aggregate pin feasibility can be reused across placements

This is a scoped structural deduction from the pinned TAP formulation, not a
novelty claim, track-routing certificate, or completed floorplanning benchmark.

## Assumptions

Inspecting `routing.py` at TAP commit
`3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb` shows nonnegative integer flow
between every chiplet/port pair, shared incoming/outgoing port capacity, demand
conservation, and a one-hop constraint for the `nppl` cases. Manhattan distance
appears in the objective. The inspected formulation does not impose a geometric
edge exclusion, maximum link length, or shared track congestion capacity.
The three published cases in our source ledger all select `nppl`.

## Necessary and sufficient condition in this abstraction

Let chiplet i have port capacities c_ip and incident directed demand
`d_i = sum_j (R_ij + R_ji)`. For a complete direct pin graph with splittable
integer demand, feasibility is equivalent to `d_i <= sum_p c_ip` for every i.

Necessity follows by summing the shared port-capacity constraints at i: every
required incoming or outgoing unit consumes a pin there. A violation is an
explicit single-chiplet cut certificate.

For sufficiency, process each directed demand in any order. Select a nonempty
source and sink port, send the minimum of remaining demand and their residual
capacities, and repeat. At either endpoint, remaining total capacity is at least
the total incident demand not yet processed. Therefore neither endpoint can run
out before its demands are delivered. All amounts remain integer. Every unit is
direct, so one-hop and conservation constraints hold. Each individual flow also
respects the upstream source-port upper bound.

The condition contains no coordinates. Feasibility can therefore be reused for
every geometrically legal placement with the same demands and capacities;
rotations that merely permute the ports preserve the condition. Wirelength
optimization still depends on coordinates and can remain nontrivial. Geometry
and thermal feasibility are not certified by this result.

## Checked source cases

`tools/audit_tap_capacity.py` reproduces the source's 45 um bump-ring sizing and
floor-rounded four-port capacities without executing upstream code. All three
cases admit a constructed integer witness. The saved witness is independently
summed to verify exact demand delivery and shared port usage:
[tap-direct-capacity-audit.json](evidence/tap-direct-capacity-audit.json).
The paper's Table I identifies these integer demands as wire counts in its
routing abstraction (see the updated source ledger). The data rate and complete
physical signal/clock/return allocation remain unresolved; this check does not
prove a bandwidth requirement or detailed routing feasibility.

This explains why merely enlarging these placement domains cannot create
placement-dependent routing infeasibility under the same model. A new benchmark
must identify a physically justified source of restricted reach, port eligibility,
escape capacity or shared routing resources before expecting that phenomenon.
Do not manufacture it by reducing arbitrary capacities. Apply any justified
extension to every baseline and keep the original formulation as a separate
reference. This deduction is useful for feasibility reuse and for selecting the
next benchmark; it does not by itself establish a new optimization method.
