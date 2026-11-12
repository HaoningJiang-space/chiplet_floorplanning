# Case and physical-model acceptance: bounded findings

The user's 2026-11-12 question was whether the physical problem is actually
closed before interpreting algorithm results. This review reads the current
implementation and original papers; it does not change the running R3 model.
Start/fetch reference: `ec10483d9cbd40c5766157a448ea613226881e2a`, remote unchanged.

## 1. What the cases represent

The [machine-readable receipt](evidence/case-physical-acceptance.json) compares
every chip's source dimensions, power, and the complete demand matrix with the
frozen R3 domain. All match the pinned TAP configuration files.

| Local case | Composition / purpose | Chips | Power | Carrier |
| --- | --- | ---: | ---: | --- |
| ascend910 | Ascend-inspired processor, I/O and memory; weak thermal-sensitivity control | 6 | 350 W | 50 x 50 mm |
| micro150 | CPU/DRAM topology with four 150 W compute chiplets; strong interaction test | 8 | 680 W | 50 x 50 mm |
| multigpu | Conceptual CPU/GPU/HBM topology; heterogeneous geometry and thermal/communication tradeoff | 6 | 755 W | 50 x 50 mm |

These are published case-study inputs, not independent product measurements.
Their roles follow the earlier fixed-input sensitivity diagnosis, not selection
of whichever case favors the new algorithm. Preserve the weak Ascend case.
The present 50 mm configuration is not the paper's default 45 mm experiment;
the original paper explicitly allows other sizes. See the
[paper/experiment comparison](paper-experiment-comparison.md) and
[source ledger](evidence/tap-source-ledger.json).

ATPlace's ten imported cases are a separate family: 6–61 dies, source-specific
rectangular carriers, per-net pin offsets and different total powers. They were
constructed by the paper's authors. Passing the importer does not mean their
placement/thermal experiments already ran. Keep Case1/6/10 as the previously
declared 6/20/61-die extension; do not replace their carriers with 50 mm squares.

**Acceptance:** source identity and input preservation pass for the current
three cases. Paper-identical reproduction and commercial-system validation are
not claimed. The imported larger family has passed parsing only.

## 2. Which physical problem is closed

For a layout x, the actual code builds moving silicon/microbump regions and
the fixed package layers, maps the fixed per-chip power to the original core
areas, and solves `A(x) * theta = P(x)`, with `T = 45 C + theta`.
Material and power boundaries follow geometry rather than rounding chip edges
to coarse occupancy bins. Power sums stay 350/680/755 W when a chip moves.

Every internal connection uses Fourier conductance
`G = area / (distance_i/k_i + distance_j/k_j)` with two half-cell distances.
The reciprocal edge is inserted in both equations. At the top surface,
`G_top = area / (t_sink/(2*k_sink) + 1/h)`; all other external faces are
adiabatic. These are a closed steady linear boundary-value model under its
declared assumptions. Missing leakage or timing feedback does not make this
particular prescribed-power thermal problem mathematically underdetermined.

Boundary semantics are explicit: the sink top is 200 x 200 mm, h is
2777.7778 W/(m2 K), so **surface convection resistance is 0.009 K/W**.
This is not a 0.1 K/W total boundary on that enlarged surface. The pinned
TAP `passive_interposer.py` explicitly scales `r_convec` by sink area to keep
h fixed, consistent with the paper's Section III-A. Thus this is not a newly
discovered unit bug. At steady state the area-average *external surface* rises
by 3.15/6.12/6.795 K for the three powers. Those values are neither die peak
temperatures nor the sink-cell-centre temperatures; solid conduction adds
temperature drop. Do not compare temperatures from another paper without
aligning its area, h/resistance convention and sampling plane.

Existing evidence checks source mapping, total heat rejection, positive
temperature rise, reciprocal/passive conductances, boundary-independent internal
coefficients and original-equation residual. HiTS/direct agreement validates
the solve of the same matrix, not the empirical accuracy of that matrix.
See [FV contract](tap-fv-contract.md), [admission](tap-fv-admission.md), and
[source-superposition diagnosis](tap-sensitivity-results.md).

Important modeling assumptions remain: constant scalar effective material
properties (including source square-fraction composites), uniform core power,
zero extra contact resistance, underfill in gaps, one die-layer thickness cell,
no radiation, no temperature-dependent leakage, and steady operation. The
reported peak is at power-layer cell centres (die midplane z=0.465 mm), not a
measured transistor junction. No independent full-package layout-ranking
validation has yet established robustness to reasonable material/boundary
uncertainty. Same-matrix agreement cannot supply that missing evidence.

**Acceptance:** the simplified heat-conduction problem and numerical bookkeeping
are connected and checked. Physical fidelity of an actual package, continuum
ranking stability for close candidates and full thermal–timing coupling remain
open. This accepts model-scoped algorithm experiments, not device qualification.

## 3. Where the current decision chain ends

`prepare_tap_fv.make_case()` deliberately emits empty `ports_mm` and `links`.
Its zero RC schema placeholders are unused; they do not assert zero physical
wire resistance. The algorithm's second objective is calculated separately from
chip centres and the sourced wire-count demand matrix. There is no pad route,
channel delay, bandwidth feasibility, I/O energy, or OpenSTA call in this R3
evaluator. Existing timing/routing modules elsewhere in the repository do not
automatically become part of this batch.

Therefore current R3 answers: **which search policy finds lower modelled peak
temperature under the same centre-distance proxy budget and thermal-query
allowance?** It cannot answer whether a fabricated thermal–timing implementation
is faster, meets a clock target, or closes detailed routing.

## 4. Next acceptance, without a new calibration campaign

Update: R3 is now [complete](tap-online-r3-results.md), and the first
[Case1 pin/geometry/thermal acceptance](atplace-case1-acceptance.md) has passed
on three fixed layouts. This does not alter the R3 evaluator described above.
Its uniform CPU rotation leaves the thermal problem unchanged while changing
the pin objective; future search must keep full orientation states separate
from thermal-cache equivalence. Optimization and larger-case coverage remain open.

The sequence was to finish R3, then connect one declared pin-level case to legal
placement and rotated pin distance with explicit package/boundary assumptions.
Keep that bounded acceptance before extending to 20/61 dies. For a stronger physical
claim, compare only a small set of relevant final layouts against an independent
matched thermal model or a bounded boundary/material sensitivity check; examine
whether the decision changes, rather than demanding arbitrary tiny temperature
error. Actual timing needs a separately defined interface and channel model.

Do not tune powers, cooling, temperature ceilings or cases to manufacture a
positive algorithm result. Each new acceptance records its evidence, scope and
remaining uncertainty in the [Overall record](overall-research-status.md).
