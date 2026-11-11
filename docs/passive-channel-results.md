# Local ideal-channel mechanism results

The final 96-record analysis set passes the preregistered numerical screens on
12 conditions, with 24 new runs and 72 verified reused records. This closes a
discrete passive-channel **numerical** milestone; real PHY, channel extraction,
pad characterization and temperature-dependent timing remain unqualified.

The session started from `dd4aac8`. Session-start and pre-milestone fetches both
succeeded; origin/main remained `c124aa982eb97f49a7f4be907554c94436ace2d2`.
The validated tool foundation was committed locally as `dc0c5bf` during the
research, as requested. Experiment sources, executable/runtime, decks, logs and
waveforms are hash recorded. All runs were local; no push or remote CI.

## What was compared

Lengths 1/3/6 mm, Thevenin drivers 25/100 ohm and linear source 10–90% slews
100/600 ps give 12 cases. Both models use the same declared geometry, source,
constant receiver capacitance and reference planes. The only circuit-model
difference is whether external series inductance is retained. RC is the L=0
reduction, not a separately fitted geometry. The source is constructed, not a
calibrated pad. The declared 1.117215037 pF receiver value follows the previous
STA representation of the Liberty scalar 1.117215 pF; trailing digits do not
represent measured capacitance accuracy.

See the [original plan](passive-channel-plan.md),
[precision/storage follow-ups](passive-channel-precision-plan.md) and
[machine-readable evidence](evidence/local-passive-channel.json).
Production STA and thermal solvers were not modified.

## Numerical result, including failures

| Stage | New completed runs | Reused records | Result |
|---|---:|---:|---|
| Original trapezoidal attempt | 37 | 0 | 37 passed; next run timed out; remaining 58 unattempted |
| Complete Gear baseline | 96 | 0 | 69/96 passed |
| Uniform fast-edge step refinement | 48 | 48 | 83/96 analysis records passed |
| Strict error-control diagnostic | 2 | 4 encountered before stopping | Two new passes, one timeout, one explicitly interrupted run; unfinished sweep |
| Cost-control pilot | 1 | 0 | Original numerical gates passed |
| Same-run text/binary control | 1 | 0 | 16066 x 20 values agree within 4.44e-16 |
| Final fast-RLC precision/storage sweep | 24 | 72 | **96/96 analysis records passed** |

There are 209 completed simulator runs including the two diagnostic controls,
two process timeouts and one deliberately interrupted run. Reuse is not counted
as new simulation. Original failures remain failures. The first runner lost the
timeout's captured stdout before writing it; that missing log is explicit.
Later runs stream logs to disk and preserve timeout records.

The Gear baseline's failures matter: 24 fast RLC records exceeded the endpoint
waveform screen despite very stable 50% crossing times, and three short RC
coarse records exceeded the charge screen. Reducing maximum steps to
0.125/0.0625 ps fixed the RC cases but left 13 waveform failures. In short-line
RLC cases, the adaptive steps near the largest discrepancy were already below
the nominal maximum. A half-step scalar-delay check alone was insufficient.

A stronger precision diagnostic passed two cases but generated million-sample,
multi-GB text traces and hit a process limit. A separately declared cost control
then passed at reltol=1e-8, abstol=1e-14 A, vntol=1e-9 V, chgtol=1e-18 C,
trtol=1, Gear maximum order 2. These settings were fixed for all 24 final fast
RLC runs. All physical coefficients and external acceptance gates stayed fixed.
This combined change does not identify a single causal solver option or explain
the original trapezoidal timeout.

Native binary export preserves every selected vector at every adaptive sample;
no linearization, decimation or downsampling is used. The same-run storage
control validates the reader against text, with explicit column/shape checks.
Binary archives are gzip compressed and decompressed hashes rechecked. A paired
1 mm/N32 control has the same 488034 samples and endpoint error for text/binary;
the process including export took 55.422 s and 9.141 s respectively. This is an
observed control, not a general performance benchmark. Final analysis archives
occupy 2,676,438,953 compressed bytes, with earlier evidence retained separately.

## Final checks

| Check | Observed maximum or count | Predeclared screen |
|---|---:|---:|
| Total integrated charge residual / (Ctotal VDD) | 2.322e-6 | 1e-5 |
| Local-node integrated residual / (Ci VDD) | 1.306e-5 | 1e-3 |
| Energy residual / (Ctotal VDD²) | 3.805e-6 | 5e-4 |
| Independent ODE vs SPICE, both endpoint waveforms | 0.164135 mV | 0.33 mV |
| Corresponding 10/50/90% crossings | 0.002339 ps | 0.1 ps |
| Half-step change in delay or slew | 0.002121 ps | max(0.1 ps, 0.25%) |
| N16 to N32 change in delay or slew | 0.011326 ps | max(0.1 ps, 0.25%) |
| MNA vs independent pi-section cascade | 9.078e-13 absolute complex H | 1e-9 |
| N32 vs continuum at five specified frequencies | 4.27106e-4 absolute complex H | 5e-4 |
| Fine configurations with unique crossings | 24/24 | retain any ambiguity |
| Deliberately corrupted ledgers detected | 5/5 | each must fail a conservation gate |

Temporal and spatial comparisons pass in all 24 case/model groups, using one
consistent method/tolerance set within each comparison. The independent state
solver uses matrix-exponential propagation with the same PWL breakpoints. The
frequency comparison includes the same source resistor and receiver load.
Neither solver is an independently calibrated electromagnetic reference.

Charge and energy balances are evaluated throughout each transient, including
driver loss, wire loss and remaining electric/magnetic energy. Negative source
power is allowed when energy returns to the ideal source. Controls reverse a
source-current sign, omit or duplicate receiver charge/energy, omit magnetic
energy, or reverse one branch current; all are detected. Analytic one-capacitor
RC response/energy, zero-L limit and invalid-element tests also pass.

These are finite sampled numerical screens, not rigorous error bounds. Five
frequency samples do not certify a continuous band or the full continuum
transient. Finite ladders do not reproduce an exact Maxwell wavefront. Positive
R/L/C and the conservation identity establish model passivity, not real hardware
accuracy. Very small reported differences should not be interpreted beyond the
declared numerical screens, much less as measured silicon precision.

## Mechanism and timing implication

The largest absolute RLC-minus-RC 50% channel-delay difference is **6.709661 ps**,
at 6 mm/25 ohm/100 ps. The corresponding largest absolute change in skew relative
to the same-parameter 3 mm clock is **3.438360 ps**. With a 100 ohm source and
100 ps slew, the 6 mm rise-delay change instead is **-1.032148 ps**. Source/load
dynamics matter: adding inductance need not increase a particular threshold
delay. There is no universal flight-time constant to add to STA.

Equal 3 mm data/clock channels cancel common delay changes in this model.
For explicitly frozen same-edge pairing and all other timing quantities fixed,
delta setup contribution = -delta skew, delta hold contribution = +delta skew.
These are conditional channel contributions, not full-lane setup/hold results.
No clock period was invented to manufacture a feasibility failure. The existing
opposite-edge buffered/inverted GPIO contract remains a different experiment.
Small rise/fall differences can include the finite settling history of the
declared pulse; complete settling was not assumed by the energy ledger.

## Remaining scientific boundary

The next question remains: **when does a reduced channel model preserve an
interface's timing-feasibility decision?** This experiment supplies a checked
numerical instrument and conditional effects. It does not supply a sourced
hardware margin or model-error bound. Obtain geometry/material/return-path and
channel evidence, a compatible driver/receiver contract and switching criteria,
then declare a decision tolerance before comparing feasibility or thermal
placement rankings. Constant-R external-L models omit return resistance,
internal inductance, frequency-dependent loss, fringing, bumps and coupling.
Original pad characterization/PEX and thermal boundary calibration remain open;
hot-pad timing and optimizer admission remain false.

The existing ChatGPT review was used through `codex-chatgpt-skill` for protocol,
failure handling and final reasoning review. Its advice was checked against
actual record counts: 72 reused final records come from the **83/96 refined
matrix**, not the earlier 69/96 matrix. The reviewer did not independently run
these experiments. [Review conversation](https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865).

## Local reproduction

Use the pinned Windows environment described in `windows-local.md`. No PDK or
OpenSTA is needed for these passive circuit experiments. Choose fresh output
directories; the tools refuse to overwrite existing experiments.

```powershell
. ./tools/windows_env.ps1
python tools/validate_passive_channel.py --integration gear `
  --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe `
  --output results/repro-channel/matrix-gear
python tools/refine_passive_channel.py `
  --baseline results/repro-channel/matrix-gear --output results/repro-channel/matrix-refined
python tools/refine_passive_channel.py --balanced-rlc `
  --baseline results/repro-channel/matrix-refined --output results/repro-channel/matrix-balanced
python tools/summarize_passive_channel.py `
  --input results/repro-channel/matrix-balanced --output results/repro-channel/summary.json
```

The historical first aborted attempt and diagnostic controls are recorded under
`results/passive-channel/`, including their frozen source snapshots. The report
renderer is specific to this milestone and consumes that retained history.
Final validation: **108 unit tests passed**, basic two-chiplet CLI power 3 W,
reference peak 34.1886 C, explicitly uncalibrated thermal model and timing not run.
