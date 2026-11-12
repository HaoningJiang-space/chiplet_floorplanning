# First integrated floorplanning decision benchmark

The same design now runs from rotated physical terminal coordinates through
finite shared routing, layered thermal fields, unique SPEF and complete
temperature-dependent OpenSTA setup/hold. Within the declared core-boundary
model and finite placement domain, all four tested conditions have **zero
timing temperature cost**. There is no evidence here that a joint optimizer
is needed. This is not a physically qualified Pad/package prediction.

## Fixed experiment and the initially open bound

The experiment freezes twelve explicitly listed placement/rotation combinations,
two routing orders and four conditions before evaluation. Rotations of the
three dies are correlated by the listed domain; this is not enumeration of all
independent rotations or continuous positions. One TX, two RX, four lanes each,
one shared forwarded clock and explicit VDD/VSS landings remain fixed. Clock
period is 20 ns throughout, with rising launch and opposite-edge capture.

Of the 96 frozen combinations, 72 produced admitted routing/timing results;
24 were greedy search failures, all at the three 180-degree layouts. They
remain **unknown**, not certified impossible. Every successfully routed pair
passed reference and feedback setup/hold. The nominal thermal lower bound was
66.353202209 C, while the best found feasible upper bound was 66.440122030 C.
The resulting 0.086919821 K gap was a search gap, not demonstrated timing cost.

A separate, bounded routing-order search at the thermal minimum used a frozen
64-order sequence with seed 20261111. Its second attempt found a legal route.
The same order was then evaluated under each of the four unchanged physical
conditions. All four witnesses passed every lane. These four additional calls
are proof evidence, excluded from the original equal-budget comparison.

| Condition | Coarse-grid thermal minimum C | Feedback worst setup ns | Feedback worst hold ns | Exact model DeltaT K |
|---|---:|---:|---:|---:|
| Nominal, 3 W, h=1000 W/(m2 K) | 66.353202209 | 9.613122940 | 10.134310722 | 0 |
| TX power x1.25, 3.375 W total | 72.009408353 | 9.614982605 | 10.135390282 | 0 |
| h=800 W/(m2 K), 3 W | 75.728739820 | 9.616043091 | 10.136423111 | 0 |
| Extra package input load, 25 fF/sink | 66.353202209 | 9.619097710 | 10.118808746 | 0 |

The optimum is `slot1_rot180`: TX at (2.5,3), RX0 at (5,0.5), RX1 at (7,5)
mm, all rotated 180 degrees. At nominal conditions its reference worst setup
is 9.599631310 ns; feedback changes it by +0.013491630 ns. These are actual
STA results using local tables and channel R, not a geometry timing penalty.

The proof is limited but stronger than an observed portfolio minimum. With
route-independent fixed heat sources, the minimum over all twelve thermal
solutions is a lower bound for any routed/timing-feasible solution. A feasible
witness at that minimum reaches the lower bound. Thus arbitrary additional
routes within this declared fabric cannot improve that numerical objective.
No claim is made about placements outside the frozen twelve, real package
rules, model uncertainty, or a fully characterized interface.

## Numerical and semantic checks

- 5,248 complete STA paths cover rising/falling setup/hold for all eight lanes,
  reference and feedback cases, and selected refined-grid cases. Bounded NLDM
  interpolation and independent path arithmetic differ by at most 2.77e-6 ns.
- 164 timing executions received an independent polarity-specific RC moment
  audit using their actual rise/fall Liberty input capacitances. All passed:
  maximum wire-delay error 1.78e-6 ns within recorded float32 absolute-path
  resolution; maximum slew error 7.04e-8 ns. Doubling R without changing the
  saved STA observation is rejected. This checks the declared one-pole model,
  not its accuracy against distributed waveforms or measurements.
- Unique wire/via/extra package shunt C is exported once; Liberty receiver C
  remains separate. The shared clock is one conductor tree and one driver.
  Temperature-dependent positive R preserves passivity. Fixed-input thermal
  power balance passes. The models do not close the whole electronic energy
  budget or model temperature-dependent leakage and route loss.
- Existing shared-routing regressions still pass all seven positive cases
  (1,824 paths) and both missing/doubled-clock-capacitance negative controls.
  Initial unit suite: 182 passed. After the proof-admission fixes below, 189
  passed; the documented basic CLI case also passed.

## Decision-focused mesh check

All twelve placements were recomputed at 2x and 4x planar resolution for each
of the three distinct thermal problems: 72 additional thermal solves. The
extra-load condition has the same fixed-power heat problem as nominal. The
thermal minimum remains `slot1_rot180` in every sweep.

| Nominal resolution | Best peak C | Runner-up peak C | Gap K |
|---|---:|---:|---:|
| 20x16 requested | 66.353202209 | 66.440122030 | 0.086919821 |
| 40x32 requested | 66.280854392 | 66.368058191 | 0.087203799 |
| 80x64 requested | 66.266338548 | 66.356845788 | 0.090507240 |

The best/runner-up difference changes by 0.003303441 K between the final two
grids, much less than the observed 0.090507240 K difference. The nominal
optimal witness also passes paired STA at both refined resolutions. This
supports the ranking on the tested grids; it is **not** a rigorous continuum
error bound, thickness convergence, external thermal validation, or a bound
on uncertain material/contact/convection parameters.

## Baselines and scientific interpretation

Thermal-first, timing-first and sequential filtering use the same original
24 evaluator calls per condition and find the same feasible minimum. These
full-budget traversal controls establish no efficiency or optimizer advantage.
Adding an adaptive route witness improves the discovered thermal objective;
it diagnoses search incompleteness, not a benefit of electrothermal coupling.

The conditions here are a finite mechanism sensitivity set, not a calibrated
operating phase diagram. Fixed-power load variation deliberately does not
recompute dynamic switching heat; electrical loading and externally prescribed
heat are independent inputs. A real workload must add activity, supply energy
and driver/channel dissipation consistently before extrapolating this result.
The existing Pad SPICE/Liberty mismatch, same-reference-plane waveform checks,
core temperature interpolation accuracy, measured package rules/boundaries,
and independent heat-field verification remain open. Goal 01 is not yet fully
physically validated. No tighter artificial clock or fitted thermal stress was
introduced to obtain a positive cost.

## Reproduction and evidence

The GitHub-only Chat review at `5e6ef7c` enumerated all 43 reachable commits,
read the four changes since its prior review and the eight principal core
modules/six experiment tools. It independently confirmed the finite-domain
zero-cost argument, and identified three admission gaps: a witness could use
a different executable/PDK, the generic proof function did not require the
expected layout IDs, and the renderer did not bind attached audit hashes.
The reviewer did not execute tests or receive local raw logs/waveforms.

The fixes leave all original solver results unchanged. A benchmark now checks
the actual selected model directory against every locked PDK file; a witness
must match both the frozen executable and full PDK manifest before evaluation.
The merge also checks every saved timing receipt's executable/source identity,
generated libraries, netlist, SPEF, script and log against their recorded hashes.
The independent channel audit verifies those exact inputs before reading pin C.

Proofs require an explicit complete layout domain and a single expected
condition. Calls without a declared domain return subset statistics with no
optimality/empty-set certificate. The experiment admission layer additionally
requires the exact original layout x profile x routing-policy ledger, binds
saved configuration/placement inputs to that frozen experiment, and recomputes
the summaries rather than reusing old certificates. The renderer verifies
benchmark/witness/thermal/channel associations and per-STA receipt hashes;
the new evidence includes a content-hash manifest for 106 evaluator receipts
and 164 timing receipts. Missing layouts, wrong runtime/PDK, modified saved
libraries, mislabeled configurations and unrelated audit files are rejected
by negative tests. This protects against accidental evidence mixing; it is
not an authenticity signature or a replacement for independent reproduction.

The original 164 channel audits were rerun with these admission checks in
`integrated-channels-v2.json`; all still pass and the doubled-R negative control
still fails. All four numerical zero-cost proofs survive the stricter merge.
A separate same-machine repeat of the nominal witness produced an identical
complete saved report, including input/thermal/STA input and log hashes. This
does not establish cross-platform bitwise reproducibility or physical validity.

```powershell
. ./tools/windows_env.ps1
python tools/benchmark_floorplanning.py --output results/decision-benchmark
python tools/find_floorplan_route_witness.py results/decision-benchmark --layout-id slot1_rot180 --output results/decision-search
python tools/evaluate_floorplan_witness.py results/decision-benchmark results/decision-search/report.json --output results/decision-witness
python tools/audit_floorplan_thermal_domain.py results/decision-benchmark --output results/decision-thermal.json
python tools/audit_integrated_channels.py results/decision-benchmark --additional-run results/decision-witness --output results/decision-channels.json
python tools/render_floorplanning_benchmark.py results/decision-benchmark results/decision-witness --thermal-audit results/decision-thermal.json --channel-audit results/decision-channels.json --output results/decision-report
```

The immutable local runs are `integrated-decision-v1`, `integrated-witness-v1`,
`integrated-thermal-domain-v1.json`, and `integrated-channels-v2.json` under
`results/physical-calibration`. The
[compact tracked evidence](evidence/local-integrated-decision.json) records
all coarse candidates, bounds, source/PDK hashes, numerical checks and refined
thermal results. Raw libraries, waveforms, route trees, thermal arrays and STA
logs remain local. The initial integrated implementation was published as
`2fb2d74`; the benchmark freezes actual source hashes because later decision
and package-load additions were not yet committed when it started.
