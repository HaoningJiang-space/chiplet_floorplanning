# Published-method availability screening, 2026-11-12

This bounded primary-source search complements the TAP source audit. It is not
an exhaustive SOTA survey or a performance comparison. No external optimizer,
training job or new thermal experiment was run. Main was successfully fetched
at `e5798d7`; the ongoing v4 pilot remains unchanged.

## Most actionable additional candidate: ATPlace2.5D

The [older package](https://github.com/Brilight/ATPlace_pub) redirects readers
to [PKU-IDEA/ATPlace_pub](https://github.com/PKU-IDEA/ATPlace_pub). Its current
README describes public placement code and explicitly notes a thermal backend
change from the original paper. Therefore its current results must not be
called an exact reproduction of ICCAD 2024 temperatures.

Remote HEAD `fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df` was cloned without checkout
to ignored `local/upstream/ATPlace_pub`. The pinned Git tree contains
`src/opt/initialization.py`, `nonlinear_place.py`, `conjugate_grad_opt.py`,
`place_obj.py`, `legalization.py`, and ten case directories. This establishes
source availability, not local executability or methodological compatibility.
The README identifies geometry, power and pin-offset inputs; it describes
Gurobi/CBC solver choices and an ATSim Linux executable dependency.

Next inspect the actual objectives, initialization, continuous relaxation and
legalization interfaces. Before any comparison, decide whether to compare an
adapted optimizer with shared evaluation or a full native pipeline whose final
layouts receive common evaluation. Those answer different questions. Account
for model training, legalization and failed runs; retain physical case sizes.
The pin-based inputs are also a candidate for scaling beyond our 6/8-chiplet
TAP workloads, subject to provenance and unit checks.

## Other screened families

| Method | Primary evidence read | Current disposition |
| --- | --- | --- |
| TAP-2.5D | Pinned source audit in `tap-published-baseline-audit.md` | Coordinate-policy component implemented separately; full adaptation still pending. |
| DiffChip | [IBM ECTC 2025 publication page](https://research.ibm.com/publications/diffchip-thermally-aware-chip-placement-with-automatic-differentiation) | Differentiable thermal/placement method; optimizer code availability was not established by this bounded search. Gradient and regularization costs require separate accounting. |
| RLPlanner | [Author repository](https://github.com/weiweihook/RLPlanner), HEAD `a75abf0b167a316dc5e2dd8b8d3d926114039271` | Visible root lists README/config/results; an executable placement/training implementation was not established. Do not infer completeness from a GitHub URL. |
| MaskPlace2.5D | [Author repository](https://github.com/xunk33333/MaskPlace2.5D), HEAD `897593e62da057affeffa611384068697e9cbed4` | README explicitly withholds core placement code and describes a compact thermal-model implementation. Not currently admitted as a directly runnable placement baseline. |
| Floorplet | [Author preprint](https://arxiv.org/abs/2308.01672) | Performance-aware framework involving Gem5. Relevant context; direct compatibility with this fixed thermal/span task is not established. |
| ChipletPart | [Author repository](https://github.com/ABKGroup/ChipletPart) and [paper](https://doi.org/10.1145/3796532) | Joint partitioning/technology/floorplanning scope; inspect the floorplanner separately rather than comparing whole partitioning objectives with a fixed-chiplet placement task. |

The MaskPlace publication reports larger benchmarks and a learned fast thermal
pipeline ([publisher abstract](https://www.sciencedirect.com/science/article/abs/pii/S0167926026001513)).
These reported improvements are not our measurements, and changing both policy
and evaluator cannot isolate optimizer quality. No quoted performance number
is used as a baseline score here.

## Decision for the next review

Finish the present 45-run mechanism pilot first. Ask R2 to assess both its actual
results and the proposed TAP/ATPlace comparison paths. A credible method claim
still requires a published optimizer, shared physical assumptions, declared
representation differences, end-to-end cost, ablations and larger held-out
workloads. Neither this availability audit nor the current small pilot meets
that entire requirement. Missing code in one candidate does not justify ending
the comparison effort: ATPlace's public optimizer is the next concrete source
to inspect.

## ATPlace interface audit at the pinned source

Read directly from Git objects; no module import or execution. The relevant
files are `src/opt/place_flow.py`, `place_obj.py`, and `legalization.py` at
`fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df`.

- The placement flow initializes through an ILP, perturbs orientations,
  runs continuous optimization, snaps orientations, and legalizes coordinates.
  It retries initialization with a changed `overflow_init` until a result is
  returned. An adapter needs an outer attempt/time limit and a saved retry
  history; an unsuccessful attempt is not proof of global infeasibility.
- The thermal callback receives tensors `(x, y, size_x, size_y, powermap)` and
  returns temperature rise; the objective adds ambient. Effective dimensions
  are relaxed mixtures of orientations. The objective combines wirelength,
  density and a temperature penalty, and differentiates through that callback.
  Our discrete FV/HiTS evaluator is not a drop-in differentiable replacement.
  A trained common-model surrogate would be a declared adaptation with charged
  training data/cost and final direct evaluation, not unchanged upstream ATPlace.
- Both legalization implementations use continuous centre variables. Binary
  separation variables do not enforce our 1 mm centre grid. Rounding a native
  result can violate separation/boundaries, so it is not a legitimate silent
  conversion. A same-domain variant needs explicit integer-grid legalization
  with the common expanded footprints and gap, followed by independent checking.
- Legalization tries a wirelength/displacement objective and may retry with
  displacement alone. Its returned final layout must be thermally reevaluated:
  the relaxed pre-legalization objective is not the final layout score.
- CBC accepts the status labelled Optimal; Gurobi accepts a positive solution
  count. These wrappers return positions or None, not a complete proof ledger.
  Preserve raw solver termination and independently check any incumbent before
  reporting it as feasible; None must remain unknown without a solver proof.
- `place_flow.py` sets environment/PyTorch threads to 64 at import. Do not import
  it inside our measured pilot. A future local runner needs explicit resource
  control and must count initialization, training, optimization and legalization.

This audit identifies actual adaptation work rather than excluding the method.
The proposed review choice is between a common-grid ATPlace-derived variant
and a separately labelled native-domain pipeline comparison. A native continuous
pipeline cannot establish same-domain optimizer superiority over this grid pilot.
The source remains untouched, and no learned model or native pipeline was run.

## Larger-case input inventory

All ten pinned `.blocks`, `.power`, and `.nets` files were read directly from
Git. Power-record counts match declared hard-block counts; net-degree record
counts and their sums match declared net/pin totals. Raw source-byte hashes and
counts are preserved in [the inventory](evidence/atplace-source-inventory.json).
This checks counts, not complete parsing, name consistency, port legality,
placement feasibility, physical qualification or measured workload provenance.

| Case | Chiplets | Interposer (mm) | Power (W) | Nets |
| --- | ---: | --- | ---: | ---: |
| 1 | 6 | 42 x 42 | 780 | 3168 |
| 2 | 6 | 55 x 52 | 370 | 3520 |
| 3 | 8 | 39 x 39 | 680 | 8448 |
| 4 | 11 | 57 x 59 | 1535 | 7040 |
| 5 | 12 | 37 x 37 | 1020 | 7392 |
| 6 | 20 | 49 x 53 | 852 | 5632 |
| 7 | 28 | 30 x 25 | 260 | 2816 |
| 8 | 36 | 26 x 23 | 240 | 2948 |
| 9 | 44 | 59 x 61 | 1548 | 7656 |
| 10 | 61 | 47 x 47 | 1006 | 5280 |

All listed nets have degree two and all cases declare zero fixed terminals.
The inspected Case1 pin records have signed percentage offsets; retain their
source units and rotations instead of replacing them with chip centres.
These are published benchmark inputs, not newly verified commercial devices.
Case dimensions and power totals differ from our original TAP family and must
not silently inherit its 50 mm geometry or thermal results. The full collection
offers a concrete scale-extension candidate without fabricating smaller routing
capacity or tighter clock targets. Selection and any common-model adaptation
must be declared before new comparative results, with the 6/8-chiplet pilot
kept separate from this larger-domain study.

### Strict input import completed

`tools/import_atplace_cases.py` now reads the pinned Git objects and validates
all ten cases: unique origin-based rectangular blocks, exact declared counts,
complete unique power/name correspondence, finite nonnegative power, two-pin
net records, known chiplet names, percentage-offset syntax and offsets inside
the chiplet rectangle. Offsets are converted using each unrotated chiplet's own
width/height with Decimal arithmetic. A quarter-turn helper rotates the offset
about the chip centre; tests cover all three nonzero rotations and reject bad
counts, unknown names, missing/duplicated/invalid power and malformed geometry.

All ten cases passed. [Import receipt](evidence/atplace-import.json) binds raw
source hashes, normalized importer hash and each generated full-input hash.
The full parsed files remain in `results/physical-calibration/atplace-import-v1`.
Reproduce in a new output directory with:

```powershell
python tools/import_atplace_cases.py --source local/upstream/ATPlace_pub --output results/physical-calibration/atplace-import-new
```

This importer intentionally leaves placement grid, gap, bump footprint,
package model and timing constraints unset. These are not available from the
three parsed file types and must come from a declared subsequent domain/model
contract. Source parsing neither creates a feasible layout nor certifies routing,
PHY capability or measured power. The ongoing pilot uses none of these new files.
