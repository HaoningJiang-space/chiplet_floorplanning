# v0.7 — legal-route counterfactual and constraint-first ranking

**The current 50 MHz control does not demonstrate a need for joint thermal–timing
optimization.** All populated routing policies retain layout 26 as the
minimum-temperature timing-feasible candidate. Shortest legal connections
largely remove the setup tradeoff introduced by the original corridors.
This conclusion is conditional on the current TT25 model, whose nominal pad
SPICE agreement is still unresolved; it is not physical validation.

See the [predeclared contract](validation-plan-v07.md),
[compact machine-readable receipt](evidence/v07-validation.json), and
[benchmark admission review](timing-benchmark-admission.md).
Local execution: 2026-11-11 UTC; Python 3.12, pinned OpenSTA 2.2.0.

## Controlled experiment

The same 27 placements, power maps, package stack, pads, TT25 libraries and
20 ns period as v0.5 are retained. Only the data/clock routing policy changes.
There is one interposer signal layer, no via or crossover, 10 um trace width,
10 um spacing and 10 um package-edge clearance. These are declared assumptions,
not foundry rules. Under-die metal routing is permitted; the reference has no
explicit routing keepouts. Independent obstacle/clearance tests cover the API.

| Policy | Geometric pass | Electrical and timing pass | Setup range (ns) | Hold range (ns) |
| --- | ---: | ---: | --- | --- |
| R1: shortest legal pair found | 27/27 | 27/27 | 8.705307–8.705314 | 11.003270–11.012710 |
| R2: original fixed corridors | 27/27 | 20/27 | 8.639044–8.771576 | 10.940630–11.071020 |
| R3: exact corridor exchange | 0/27 | Not evaluated | Missing | Missing |
| R4: feasible finite route portfolio, then least total length | 27/27 selected | 27/27 | 8.705307–8.705314 | 11.003270–11.012710 |

R1 tries both net orders and performs obstacle-aware rectilinear shortest-path
search. It is generally a heuristic for the two-net problem. For these 27 cases,
the constructed legal pair attains the sum of independent Manhattan lower
bounds; Manhattan distance alone was never accepted as a legal route.

R2 reproduces the prior 20 analyzed and 7 electrically rejected candidates and
exactly matches the old ranking runner's reported setup/hold on the same build.
Local values in the tables match the historical receipt; cross-build differences
are discussed below and are not screened with a physical-error tolerance.
R3's exchanged routes intersect on the declared layer. They are rejected before
SPEF/STA; this does not establish impossibility with a different metal stack and
properly modeled vias. R4 selects R1 for every placement in its finite portfolio,
which is not an exhaustive route-assignment optimizer. Its feasible-candidate
margin ranges remain available in the receipt.

## Which conflicts survive?

| Cohort / policy | Opposing pairs at 2e-6 ns tolerance | Pairs with margin difference >1 ps |
| --- | ---: | ---: |
| R1, all 27 accepted | 73 | 0 |
| R2, its 20 accepted | 121 | 104 |
| R4, all 27 accepted | 73 | 0 |
| R1/R4, same 20 accepted by R2 | 28 each | 0 each |

Locally R2 reproduces the review's split: 99 pairs have different TX y coordinates and
22 have the same TX y. Counts share one design/model and are not independent
replicates. R3 has no accepted cohort: its conflict count is **null**, not zero.
The common cohort includes R1/R2/R4 only and explicitly records this exclusion.

R1's full setup spread is **0.007 ps**, versus R2's **132.532 ps**. R1 still has
a **9.44 ps hold spread**: common data/clock delay does not imply all min/max
timing behavior cancels. In this case the worst margin is setup, so R1's raw
opposing pairs concern extremely small setup differences. Keep the differences
visible instead of rounding them away to claim zero conflict.

The 1 ps column is an effect-size diagnostic, **not a model error bound**.
Likewise, the thermal pair filter uses the sum of two final mesh changes as a
refinement proxy, not a certified physical uncertainty interval. No surviving
pair is asserted physically resolvable. The full physical error is unbounded.
At raw reported precision R2 has six Pareto points; treating slack differences
within 2e-6 ns as tied leaves layouts 23/24/25/26. This precision dependence is
reported, not evidence of a necessary design tradeoff.

## First CI failure and build-dependent tiny rankings

The [first CI run](https://github.com/HaoningJiang-space/chiplet_floorplanning/actions/runs/43015732814)
at `89f27c8` failed the comparison against historical local R2 slack. Its new R2
and old ranking runner nevertheless agree **exactly for every reported slack**,
with identical case input hashes, libraries and STA executable. Relative to the
local build, its largest R2 difference is 0.004 ps setup / 0.01 ps hold.
See [retained diagnostic](evidence/v07-ci-diagnostic.json).

The CI build counts 68 raw R1/R4 pairs and 115 raw R2 pairs (99 different TX y,
16 same TX y), while the local counts are 73 and 121. The common 20-candidate
R1/R4 count remains 28. All three policies' counts above 1 ps, feasible sets and
constrained thermal optima agree. Thus even printed-precision pair counts and
Pareto sets are not portable physical findings.

The corrected regression requires a fresh `--reference-ranking` report and
verifies input/build/library/clock/interface identity before demanding **exact
reported equality**. It does not raise a tolerance to pass. Historical local
differences remain separate diagnostics, and the original CI failure is retained.
No electrical, setup/hold, mesh or hot-pad qualification gate is relaxed.

## Hard constraints change the interpretation

For each policy first choose the coldest candidate from the geometrically and
electrically legal pool, **before** applying timing. Then check setup/hold and
choose the coldest timing-feasible candidate. The objective is minimum peak
temperature, with no reward for surplus positive slack.

| Quantity at layout 26 | R1 / R4 | R2 |
| --- | ---: | ---: |
| Peak temperature | 59.749036 °C | 59.749036 °C |
| Data / clock length | 3.5 / 3.5 mm | 5.7 / 3.7 mm |
| Setup slack | 8.705311 ns | 8.639044 ns |
| Hold slack | 11.007210 ns | 11.069210 ns |
| Thermal penalty imposed by timing constraints | 0 K | 0 K |

The existing thermal optimum satisfies timing for all three populated policies.
This is evidence **against necessity in this control**, not a statement that
thermal-only placement is universally sufficient. No period or score weight
was retuned to produce violations. A real timing-critical benchmark remains
unadmitted; the pinned Basilisk source review identifies concrete clock/load/
endpoint dependencies without applying another PDK's constraints to this lane.

`S_T(X)` and the thermal pair interaction
`[S_T(B)-S_T(A)]-[S_0(B)-S_0(A)]` remain **null**. Pad temperature tables have not
passed the v0.6 same-interface gate; the core-only FF model cannot fill the gap.

## Numerical checks and evaluation cost

There are 54 thermal evaluations (two meshes per placement), 297 unique route
geometries audited, and 99 actual STA invocations; 198 geometrically rejected
routes never reach STA. Exact duplicate route polylines within a placement are
aliased, not rerun. Thermal results are reused only across routing choices of
the **same** placement/power/stack/mesh because wire heating and metal-pattern
conductivity are absent. No matrix is reused across different placements.

Peak-temperature refinement change is at most 0.012534 K, below the predeclared
0.1 K gate; absolute heat-balance error is at most 8.85e-13 W. This is XY
refinement and conservation evidence, not vertical-mesh or material calibration.

One local run took 99.71 s; these are diagnostic wall times, not a speedup claim:

| Phase | Samples | Total time (s) | Median per sample (s) |
| --- | ---: | ---: | ---: |
| Mesh generation, including route input reconstruction | 351 | 0.0586 | 0.000145 |
| Thermal matrix assembly | 54 | 4.2784 | 0.078595 |
| Thermal linear solve | 54 | 2.5320 | 0.043999 |
| Route generation | 27 | 0.1119 | 0.004494 |
| SPEF generation | 99 | 0.0152 | 0.000150 |
| STA subprocess | 99 | 73.2306 | 0.736565 |
| Entire STA wrapper, including subprocess | 99 | 92.0717 | 0.933563 |

Wrapper and subprocess times overlap and must not be added. Remaining time
includes input checks, power mapping, qualification, file I/O and reporting.
Profiles include both successful and rejected attempts. The visibility-grid
router is limited to 25,000 vertices and two nets; this is not a scalability
claim for a general chiplet timing graph.

## Regression and reproduction

67 unit tests passed, including 11 new routing/constraint/reference-identity tests. Existing
16-check GPIO prototype and 6-check layout-ranking regressions passed. Both
documented two-chiplet CLI cases passed; their timing remains explicitly
`not_run` without STA inputs. The new experiment passed 9 software checks.
The original slab peak remains 34.1886068258 °C.

```bash
python -m pip install -e '.[validation]'
python tools/bootstrap_validation.py --build-sta
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two-chiplets
chiplet-floorplanning evaluate examples/layered_two_chiplets.json --output results/layered
python tools/validate_prototype.py --output results/prototype
OPENBLAS_NUM_THREADS=1 python tools/validate_layout_ranking.py --output results/ranking
OPENBLAS_NUM_THREADS=1 python tools/validate_routing_policies.py \
  --reference-ranking results/ranking/report.json --output results/routing
```

Use fresh output directories. CI executes the new experiment alongside the
existing open-case regressions. Raw case snapshots, routes, SPICE/STA reports,
phase samples and failures stay under ignored `results/`. The compact receipt
retains source/input/library/executable hashes; local source was dirty during
development and is explicitly recorded as such. No PDK assets or credentials
are published. CI success continues to mean software/regression success;
physical calibration, valid hot-pad coupling, full PVT and complete package
signoff remain incomplete.
