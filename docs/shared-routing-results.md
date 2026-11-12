# Shared routed clock: completed numerical integration stage

Implementation commits `a5416aa` and `0193807`; successful origin fetch remains
`c124aa9`. All runs stay local. The finite resource model, unique routed RC tree,
and complete multi-lane timing checks are now connected. This closes a numerical
integration stage, not the ten goals or physical package/Pad qualification.

## Finite routing resources and checkable infeasibility

The declared uniform grid uses two signal layers, 20 um pitch, 10 um trace and
landing diameter, 10 um spacing, positive layer separation and edge margin.
Different nets cannot share conductor nodes or edges. Shared branches belong
to one clock net. Tree connectivity, terminal ownership, blocked resources,
cycles and dangling nonterminal branches are checked.

| Chiplets | Data lanes | Distinct crossing nets | Feasible cut capacity | Infeasible paired capacity |
|---|---:|---:|---:|---:|
| 2 | 8 | 9 | 9 | 8 |
| 4 | 24 | 25 | 25 | 24 |
| 8 | 56 | 57 | 57 | 56 |
| 16 | 120 | 121 | 121 | 120 |

Every feasible case has a checked routing witness. Each capacity-shortfall case
has a certificate enumerating the full x-section across all layers; demand
counts distinct nets with terminals on both sides, including a multicast clock
only once. Verification recomputes the cut, preventing omitted tracks or
duplicate-clock demand. The proof is only for this finite declared fabric.

A 4x3 counterexample demonstrates that greedy failure is not infeasibility:
net A connects (0,0) to (0,2), net B connects (0,1) to (2,1). Greedy A occupies
B's only escape. Independent enumeration finds A's longer route through x=3
and B's direct route. It enumerates 2 A paths and 7 B paths. A separate 3x3
opposite-edge crossing case is exhaustively infeasible; enumeration limits
return unknown. This is graph routing verification, not floorplan optimality.

## One conductor, one parasitic contribution

The largest clock tree has 160 physical edges and 161 nodes: unique wire length
3.2 mm, versus 20.7 mm summed over source-to-sink paths. With the declared
0.2 pF/mm coefficient, its unique wire capacitance is 0.64 pF. Fifteen receiver
input pins add 0.15 pF separately. SPEF exports one driver and one copy of each
sink; OpenSTA reports the same 0.79 pF total. Charging every endpoint path as
separate metal would multiply shared capacitance incorrectly.

The coefficients 0.1 ohm/mm, 0.2 pF/mm and optional via values are assumed
passive numerical parameters. They are not extracted/measured package material,
return-path or signal-integrity evidence. The scalable fixtures have zero vias;
a separate unit control verifies via R/C ownership.

## Independent RC moments and complete timing

For each connected positive RC tree, solve the ideal-source-grounded nodal
system `G*m1=C*1`. Separately sum downstream capacitances along tree edges.
These agree as exact first moments. The timing fixture then explicitly chooses
the one-pole approximation `ln(2)*m1` and incremental slew `ln(4)*m1`, matching
pinned OpenSTA `simple_rc`. This is not an exact distributed-RC crossing time
and is not substituted into the existing real-Pad default flow.

Seven configurations complete 1,824 routed setup/hold/rise/fall path checks:
2/4/8/16 chiplets at nominal R, 2 and 16 at 100x R, and 16 with the previously
declared common-root correlation. Maximum complete-path discrepancy is about
1.08e-6 ns; the existing 1e-5 ns numerical tolerance passes. Maximum reported
conductor capacitance discrepancy is 2.1e-8 pF. Both missing-clock-parasitic and
doubled-clock-capacitance mutations are rejected.

Nominal data/short-clock increments can be below float32 report resolution.
They are explicitly counted as unresolved rather than assigned a misleading
relative accuracy. The 100x R controls resolve all tested channel increments;
they are numerical sensitivity controls, not measured PVT/temperature corners
or admissible real timing-stress benchmarks. The longest declared 16-chiplet
clock delay changes from 0.000071974 ns to 0.0071974 ns under that R scaling.

The v3 receipt retains raw routed path times separately from the fixed-cell
audit, which algebraically removes independently predicted wire increments.
Reports use raw routed slack, not the wire-removed intermediate. Earlier v1/v2
runs remain local. All source/fixture/log/parasitic records are hashed.

169 software tests and the two-chiplet CLI pass. The graph model's layer/track
geometry still lacks real die/bump escape and package design-rule provenance.
Real Pad/PHY, actual channel RLC/coupling/reference planes and whole-link power
ownership remain open, as do local-temperature coupling and joint optimization.
No timing stress or SOTA result is inferred from these synthetic controls.

## Thermal evidence and independent review

The first natural-C level-1 package transient also passed its reduction checks,
but native temperatures differ from level 0 by up to 0.98383 K (spatial component
0.94600 K). Storage-vs-spatial-contrast behavior persists in the checker window;
see `ttc-package-transient-results.md`. Spatial convergence remains open.

Before publication, the user deferred file upload and explicitly requested that ChatGPT use
its own tools to read Git history. The existing high-thinking review conversation
has actually connected its GitHub plugin and verified access to remote
`c124aa9`. It attempted local `0193807`: GitHub returned 422 (no commit for SHA),
the comparison returned 404, and its execution environment did not mount the
Windows repository. The 22 local commits are therefore outside its observed
access at that time. The user chose GitHub-only review without additional Chrome permission.
The remote review and its commit-by-commit coverage receipt are complete. It
enumerated the 14 commits from `5f82272` through `c124aa9`, matching the locally
fetched Git history and all 13 parent links. The reviewer reports reading each
commit's changed-file list/patch and inspecting the key final thermal, routing,
Pad and timing-oracle sources/evidence. This is review coverage, not formal
verification or independent rerunning of the experiments. It found no confirmed
new code bug, preserved the distinction between software success and failed
physical qualification, and identified retained historical build/regression
failures rather than interpreting later successful runs as their erasure.
The review confirms the remote implementation's restricted timing/routing domain
and distinguishes numerical invariants from physical evidence. Its actionable
priorities are consistent Pad netlist/Liberty/stimulus/reference planes, spatial
and transient package convergence, real routing rules, then a timing-constrained
temperature penalty exceeding supported model uncertainty. These are evidence
gaps, not independently confirmed new bugs in the inaccessible local code.
At that prepublication point, no completed full-local-history review was claimed
and no push or remote experiment had been requested or performed. The review
is advisory and closes no physical gate.
Review conversation: https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865.

Publication follow-up: the user subsequently required timely pushes. The 25
commits through `92c2835` were pushed and independently located by ChatGPT via
GitHub. The reviewer completed the newly accessible commit/source review,
including the shared routing/RC/STA implementation, TTC and Pad diagnostics.
It found one concrete future BE-cache protocol-checking gap, rather than an
observed wrong cached value, and no confirmed new shared-clock ownership or
energy-balance bug. Four large evidence files lacked historical patches; their
HEAD contents were checked instead. No large local raw experiment was rerun by
the reviewer. See `review-response-decisions.md` for the actual coverage,
retrospective cache check and remaining engineering fix. The earlier access
restriction is historical, not the present repository state. Pushes skip remote
CI while research computation remains local.

Reproduce with fresh local output folders:

```
python tools/validate_shared_routing.py --output results/physical-calibration/shared-routing-new
python tools/validate_shared_routed_timing.py --output results/physical-calibration/shared-routed-timing-new
python tools/render_shared_routing.py --routing results/physical-calibration/shared-routing-new --timing results/physical-calibration/shared-routed-timing-new --output PATH_TO_OUTPUTS
```

Compact evidence is `evidence/local-shared-routing.json`. Authoritative raw runs
are `shared-routing-v2` and `shared-routed-timing-v3` under the local physical
calibration results directory.
