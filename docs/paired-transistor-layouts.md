# Paired layout/routing decision sensitivity

The experiment follows the Chat review's decision-focused recommendation:
compare differences between two complete candidates before chasing absolute
SPICE/Liberty agreement. A is the thermal-minimum `slot1_rot180` witness; B is
the already routed nominal `slot1_rot90_clock_first` candidate. This compares
**placement and its actual routing jointly**, not an isolated rotation effect.
Both use the previously frozen nominal power/package assumptions.

The source/receiver electrical experiment is uniformly 25 C and 1.8 V with
the same 32 core cells, 20 ns input clock, stimuli, output loads and primitive
models. Thus this is the reference-temperature comparison, not an evaluation
of the distinct hot temperature fields below. The saved assumed-package peak
temperatures are A 66.353202209 C and B 66.440122030 C, a 0.086919821 K gap.
No physical thermal difference bound is inferred from these numbers.

Two new 60 ns SPICE runs (5/2.5 ps maximum steps) cover candidate B. A reuses
its preserved original waveforms. The comparison independently replays both,
verifies the full paired path domain, binds both RC records to saved SPEF,
and requires the actual deck's entire R/C/cell section to equal the admitted
circuit. All remaining stimuli, supplies, solver controls and output loads
must match; the consumed primitive manifests, cell netlists and executable
must also match. The old duplicated clock column in A is read according to
its preserved column list; B uses the corrected unique observation list.

## Result

Positive B-minus-A means the hotter candidate has a larger available window:

| Worst window over all lanes/edges | SPICE B−A | STA B−A | Difference between predicted changes |
|---|---:|---:|---:|
| Setup | +21.692355 ps | +29.426276 ps | -7.733921 ps |
| Hold | +9.558388 ps | +10.038377 ps | -0.479989 ps |

Minima are recomputed independently for each candidate/model, rather than
assuming the same critical lane. This explains why the worst setup and hold
windows can both improve even though an individual path's windows trade off.
Across all 16 lane/edge pairs × 2 window types, **zero ordering reversals**
occurred between SPICE and STA. The largest differential model discrepancy
on an individual path was 18.222080 ps. Halving the step changed the paired
SPICE effect by at most 0.029223 ps. This is a tested numerical sensitivity,
not a rigorous error bound or a physical uncertainty estimate.

Both tested patterns passed receiver-event and stable-output checks for every
lane. Available windows remain distinct from setup/hold slack: independent
receiver constraints, Pad/ESD, realistic channel coupling and local temperature
feedback are absent. The small observed cross-model paired discrepancy does
not qualify all unmodeled effects or all operating conditions.

The alternate `rot90_data_first` saved candidate has exactly the same RC
receipt and identical worst setup/hold STA values as `rot90_clock_first`.
It was not simulated again as if it were an independent physical case.

## Decision implication

### Third candidate: rot270

C is `nominal_slot1_rot270_clock_first`, simulated with the same full circuit,
stimuli and two maximum time steps. Its assumed-package thermal peak is
66.463536859 C. All electrical comparisons remain uniformly 25 C.

| Comparison | Worst setup change SPICE / STA | Worst hold change SPICE / STA |
|---|---:|---:|
| C minus A (rot180) | +85.140425 / +108.872771 ps | -78.041091 / -102.981567 ps |
| C minus B (rot90) | +63.448070 / +79.446495 ps | -87.599479 / -113.019944 ps |

The three pairwise comparisons have no ordering reversals across 96
lane/edge/window comparisons. These reuse three candidates and are not 96
independent experiments. For C-minus-A the maximum paired time-step change
is 0.072423 ps and the largest per-path differential model discrepancy is
45.190785 ps; for C-minus-B these are 0.067955 ps and 41.597613 ps.
The model difference is much larger than the tested step sensitivity, but
does not reverse these tested orderings. Neither quantity is a bound on
physical error. C improves setup windows while reducing hold windows; it
does not demonstrate that the cooler A is infeasible.

Evidence: [C minus A](evidence/local-paired-transistor-rot270.json),
[C minus B](evidence/local-paired-transistor-90-270.json). Reproduce using the
same commands below with `rot270` replacing `rot90`, then compare the saved
B and C runs for the second pair.

The two declared electrical models agree on this candidate comparison, while
the measured amount of the difference is model dependent. A is cooler; B has
larger worst available timing windows. This is a tradeoff, **not evidence that
the timing constraint excludes A**, and it does not change the previously
proved finite-model zero timing temperature cost. No joint-search superiority
or physical optimum is claimed. Uncertainty remains `uncertainty_unquantified`.

Next extend the same paired comparison to temperature feedback and receiver
constraints, keeping all input identities fixed. Do not shorten the period
to manufacture a failure boundary.

## Reproduce

```powershell
. ./tools/windows_env.ps1
python tools/audit_integrated_transistors.py results/physical-calibration/integrated-decision-v1/nominal_slot1_rot90_clock_first/reference --output results/rot90-transistors
python tools/compare_transistor_layouts.py results/physical-calibration/integrated-transistors-v1 results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness/reference results/rot90-transistors results/physical-calibration/integrated-decision-v1/nominal_slot1_rot90_clock_first/reference --output results/paired-transistor-layouts.json
```

[Tracked paired evidence](evidence/local-paired-transistor-layouts.json) records
every comparison and hashes of both raw/STA/placement/evaluator receipts.
Raw waveforms remain local. Constructed tests cover common-bias cancellation,
layout-dependent rank reversal, missing/duplicate paths and nonfinite data.
