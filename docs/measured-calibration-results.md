# Public measured benchmark milestone, 2026-11-11

This milestone establishes real-measurement comparisons, **not qualification of
the target chiplet package**. All experiments ran locally. Origin fetch at the
start and again before this milestone succeeded; remote remains `c124aa9`.
Admission/tools milestone: `c5fc0a6`. No push or remote CI.

## First-principles findings

1. A rising sensor temperature is evidence that storage cannot automatically be
   dropped from `P = dU/dt + Q_out`. Thirteen long experiments stop high power
   near 100 C; their endpoints are not measured constant-power equilibria.
2. Passive positive G/C and an accurate energy ledger verify a mathematical
   network. They do not establish the geometry, measurement operator or actual
   boundary condition of the hardware.
3. A parameter at a computational bound with very weak sensitivity is not a
   measured material property. A short sampling interval can still be too slow
   for the fastest thermal modes; input and sensor averaging matter.
4. DC transistor agreement does not determine dynamic Pad capacitance, PEX,
   channel reference planes, clock/data skew or real chiplet timing.

## TTC source and admission

Terraneo, Leva, Fornaciari, 2019 SAMOS; Zenodo 3345878 v2,
DOI `10.5281/zenodo.3345878`, CC-BY. The TTV-1202 test vehicle is a single-die,
4x4 heater/diode array on flip-chip BGA, with an HS483-ND copper heatsink and
P14752-ND fan. It is physically different from the repository's chiplet stack.
All 39 raw experiment files and documentation are hash locked. The 13 fast
1 kHz cases are inventoried only; the 26 long cases use 10 Hz input/temperature.

The predeclared steady screens refuse fitting: only 1/4 natural and 2/4 forced
calibration cases pass, below the frozen minimum 3. The failed schema attempt
and successful refusal remain separately preserved. See
`measured-admission-results.md` and `measured-calibration-plan.md`.

## Conditional transient fit

Use the same calibration patterns (`one`, `four`, `sixteen`, `line_1`) and nine
other patterns for prediction, per cooling group. These holdouts were previously
examined in the admission audit, so this is **not blind validation**. Fit only
five equivalent network parameters; 4 starts per group, no source or observation
offset fitting. Inputs are actual recorded powers, including early shutdown.
The fit cannot predict cutoff policy or safe operation under sustained power.

| Quantity | Natural convection | Fan |
|---|---:|---:|
| Calibration runs | 4 | 4 |
| Held-out runs | 9 | 9 |
| Calibration equal-run RMSE, K | 1.00630 | 1.46724 |
| Held-out equal-run RMSE, K | 1.64491 | 2.76817 |
| Held-out maximum absolute error, K | 26.96146 | 27.99724 |
| Held-out max outside principal switches +/-1 s, K | 6.76610 | 6.59404 |
| g_xy, W/K | 0.0682965 | 0.0700387 |
| g_z, W/K | 0.0980593 | 0.1283802 |
| g_a, W/K | 0.1538095 | 0.9618507 |
| C_cell, J/K | 0.0454705 | **0.0001000, lower bound** |
| C_bath, J/K | 81.9989 | 66.8657 |
| Log-parameter sensitivity condition number | 57.23 | **382437** |

The two fitted g/C sets are fixture-specific reductions. Differences cannot be
interpreted as changes in silicon k, true TIM or heatsink material heat capacity.
The raw relative-rank cutoff returns rank 5 in both cases, but the fan's bound
hit and weak sensitivity preclude a robust C_cell identification claim.
Holding other parameters fixed and increasing fan C_cell from 1e-4 to 1e-2 J/K
changes training RMSE only from 1.467237 to 1.468477 K. This is a conditional
objective slice, **not** profile likelihood or a confidence interval.

The 17-node generalized eigenmode solver was checked against a separate 34x34
augmented matrix exponential. Across all 26 measured predictions, the largest
normalized energy residual is 7.431e-11. The balance includes input energy,
initial/final stored energy, and analytically integrated bath heat removal;
it is not just a final temperature comparison. Both groups' four optimizations
terminated successfully; success here is a numerical solver status.

## Timing, initial state and observation limitations

The largest native-sample errors occur exactly at the principal power switch.
They do not uniquely distinguish true fast dynamics, logger timestamp/averaging,
sensor response, or spatial reduction errors. Keeping parameters frozen and
shifting the entire power input by +/-0.1 s changes held-out predictions by as
much as 14.667 K (natural) and 32.071 K (fan). These are illustrative sensitivity
scenarios, not a measured timing bound. The original all-point errors remain;
the +/-1 s excluded diagnostic never replaces them or becomes an accuracy gate.
Residuals outside that window still cannot be attributed uniquely to structure:
ambient, sensor offsets, contact variability and source uncertainty also remain.

Initial cell states are observed. Initial bath state is inferred from zero mean
cell storage, an explicit hypothesis. The pre-step 60 s mean-temperature trend
would add at most approximately 0.002127 K / 0.00000245 K to the inferred bath
temperature for natural/fan fits. This finite-window trend is not an instantaneous
derivative and cannot rule out other initial-state errors. The alternative
bath-initial scenario changes predictions by up to 1.842 / 1.422 K.

Ambient has one reported measurement per run; no ambient time series exists in
the archive. Constant ambient is an unverified condition, not an observed fact.
If varying ambient is represented with relative states, `-C*1*dTamb/dt` is
required. No ambient drift series is invented. A 0.1 K sensor resolution is not
absolute accuracy; the complete noise/covariance and calibration uncertainty
budget is missing. Observed diode temperatures are not unobserved silicon peaks.

## Pad primitives

Google's SKY130 raw-data commit
`1f7214f2f81a0629303947a07e1ec00a28ae8a33` contains CoolCAD silicon measurements.
Four files cover n/p `g5v0d10v5`, W=7 um, L=0.5 um, IDVD/IDVG, 36 curves.
The immutable existing TT models were evaluated at assumed 20/25/30 C, giving
108 complete comparisons and **10908 bias-point evaluations**. No model fitting.

At assumed 25 C, over fixed on-state selection |ID| >= 10 uA:

| Device | Measured on-state points | ID RMSE, uA | Pooled relative L2 error |
|---|---:|---:|---:|
| nFET | 1369 | 69.468 | 3.210% |
| pFET | 1289 | 47.957 | 4.680% |

These pooled on-state summaries supplement all per-curve signed-current metrics,
including low-current noise. No passing accuracy threshold is asserted.
20/25/30 C are scenarios, not the measured temperature or its confidence range.
Missing temperature, lot, layout/diffusion and probe details prevent complete
primitive qualification. No complete GPIO transient or package measurement was
compared. Four-terminal model KCL residual <=1.046e-16 A; model total DC port
power is nonnegative. Source current inferred from measured ID/IG/IB would not
constitute an independent measured KCL test, and is not used as one.

## Evidence, reproduction and next scientific question

Raw/derived local folders under `results/physical-calibration/`:
`sources`, `thermal-original`, `thermal-fit-v1` (schema failure),
`thermal-fit-v2` (steady refusal), `pad-primitive-v1`, `thermal-transient-v1`,
`transient-audit-v1`, and first/final test and CLI outputs. No failed result was
overwritten. Plans, source/deck/waveform hashes and solver settings are retained.
The two-chiplet CLI still reports 3 W, reference peak 34.1886068 C,
thermal uncalibrated and timing not_run. **119 unit tests passed.**

```powershell
. ./tools/windows_env.ps1
$env:PYTHONUTF8='1'
python tools/calibrate_measured_transient.py --output results/new-transient
python tools/audit_measured_transient.py --fit results/new-transient/report.json --output results/new-transient-audit
python tools/render_measured_report.py --output <user-deliverables-directory>
```

The renderer uses the named original milestone folders; the analysis tools
accept new output folders and refuse to overwrite experiment directories.
Reports retain `physical_model_qualified=false` and no target-package transfer.

The scientific question is which independent spatial/temporal excitations and
boundary observations can constrain thermal coupling sufficiently to preserve
layout rankings under measurement and boundary uncertainty. Before optimizer
claims, recover logger time semantics and matched fast-data cooling conditions,
measure/trace package geometry and secondary board paths, and constrain the
sensor observation operator. Pad and package electrical work still requires
complete dynamic device/PEX and measured de-embedded reference planes.

ChatGPT reviewed the plan and interpretation in the existing research chat via
`codex-chatgpt-skill`. Adopted concerns: sensor observation versus mesh peak,
conditional initial bath, missing ambient drift, fast event sampling, and
nonidentifiable material parameters. Review does not independently reproduce
the local experiments or create measurement evidence.
Final review accepted the local milestone with three explicit limits retained:
timing sensitivity does not attribute the original error, five physical
parameters have not been identified, and pooled Pad errors do not describe all
bias regions. No physical admission was granted by this review.

Sources:
- https://zenodo.org/records/3345878
- https://re.public.polimi.it/handle/11311/1099255
- https://github.com/google/skywater-pdk-sky130-raw-data/tree/1f7214f2f81a0629303947a07e1ec00a28ae8a33
- https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865
