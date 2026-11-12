# Exact six-chip decision subdomain and reusable structure

2026-11-12: fetched origin; clean `main=f6563d5`. No new thermal candidate
experiment or routing optimization was run before this domain freeze.

## Finite domain, independent choices

Keep all six Ascend910 chips, sourced cores, 350 W power, wire demands, bump
rings, 50 mm interposer, 1 mm centre grid, and 100 um expanded-footprint gaps.
For each chip independently, choose either its published first-fit centre or
that centre rotated 90 degrees about the package centre. Independently select
0, 90, 180 or 270 degrees of chip rotation. Filter per-chip package bounds,
then enumerate the Cartesian product and check all exact integer rectangle gaps.
The second anchor is a deterministic geometry construction, not a thermal or
routing-selected position. Chips need not select the same anchor index.
The larger independent domain remains in `tap-geometry-domains.md`.

Enumeration yields 131,072 products after per-chip boundary filtering:
126,144 violate overlap/gap constraints, and **4,928 are geometry feasible**.
These rejected products have explicit geometric contradictions, not failed
routing searches. All four rotation labels occur among legal layouts. This
small domain is exact and checkable, not a claim about global 50 mm optimality.

`tools/freeze_tap_decision_domain.py` publishes each chip's choices, legal
mixed-radix ordinals (last chip index varies fastest), and thermal class
representatives in [evidence/tap-decision-domain.json](evidence/tap-decision-domain.json).
The domain file's SHA is recorded. Re-enumeration is independent of temperatures.

A preliminary geometry-only construction used first-fit and +1 mm x anchors.
It gave 704 legal states/11 thermal classes but admitted no distinct 90-degree
shape orientation. Before any candidate thermal/routing evaluation, it was
replaced by the above orientation-capable construction. Both raw enumeration
results remain local (`tap-decision-domain-v1.json`, `-v2.json`). No capacities,
clocks, powers or thermal outcomes were used to choose the new anchors.

## Structural reuse: 4,928 layouts need 77 thermal inputs

For the frozen FV model, each chip has a centred uniform rectangular heat
source, a symmetric rectangular bump ring, and isotropic material assignments.
Replacing its rotation by rotation+180 leaves the absolute core rectangle,
expanded footprint, power density, material fields and package boundaries
unchanged. The conformal mesh rule depends on those same rectangles. Therefore
it leaves the discrete thermal problem unchanged, apart from floating-point
coordinate representation. Use the canonical representative to avoid duplicate
assembly/solves. This does not rely on similar peak temperatures.

The 4,928 legal states split into **77 classes of 64 states** (independent half
turns of six chips). Tests check actual rasterized power, conformal coordinates,
and active material fields for the half-turn pair, in addition to exact integer
geometry. This is a scoped reusable symmetry, not a novelty claim.

Do not transfer this thermal equivalence to routing. Asymmetric PHY locations,
port identities or return/clock assignments can distinguish the same rotations.
Nonuniform heat maps, asymmetric die materials, or different boundary assumptions
invalidate this particular reuse rule and require a new key/proof.

## Conditional full-width cut bound: cannot explain infeasibility here

The authors' [ICCAD 2018 Table 2](https://people.bu.edu/joshi/files/interposer-nw-iccad-2018.pdf)
uses 1 um wire width, 2 um pitch and 1.5 um thickness for its 65 nm interposer
model. These are reference modeling parameters, not a complete TAP process stack.

Condition on one signal layer normal to a straight full-width cut, usable over
the entire 50 mm interposer, including underneath dies. Its track count is
50,000/2 = **25,000**. Dedicated return/power resources and additional clock
conductors are not established by this calculation. Layer count, access/via
rules and actual PHY allocation remain unresolved rather than silently supplied.

For any terminal partition, the sum of demands forced to cross once cannot
exceed the total directed wire demand: Ascend 2,448; Micro150 10,240; MultiGPU
6,912. Thus this particular necessary cut test cannot reject any layout in any
of the three domains under the stated resource assumptions. The saved field
`any_single_full_width_cut_can_reject=false` records that deduction. A true
value would only mean this total-demand argument no longer rules out rejection,
not that some layout has been proved impossible.

This is not a routing-feasibility certificate. It says nothing about local
escape, shared narrow cuts, multi-commodity conflicts, via resources, length,
signal integrity or timing. Actual path loads can also cross repeatedly; the
bound concerns the unavoidable demand used in a cut lower-bound argument.
Do not treat chiplet gaps as complete graph cuts when under-chip routes exist.
Do not reduce track capacity to make the test trigger.

## Remaining benchmark work

The exact geometry domain and thermal equivalence are frozen; the finite routing
benchmark is **not yet complete**. Next freeze physical/assumed layer and via
resources, distributed bump/port access, signal/clock/return allocation and
allowed bypasses. Then construct routing witnesses or sound impossibility
certificates, and only afterward run the 77 thermal representatives for the
zero/nonzero resource-penalty comparison. Search failure remains unknown.

Validation: 261 tests and a fresh documented two-chiplet CLI passed locally.
No remote computation, algorithm claim, thermal optimum, or routability result.
