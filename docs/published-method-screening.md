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
