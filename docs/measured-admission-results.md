# Measured-data admission result, 2026-11-11

The first steady-state calibration attempt was **correctly refused** by the
predeclared data screens. This is a measurement-admission result, not a failed
thermal simulator and not a completed package calibration.

Sources are locked in `tools/measured-sources.lock.json` (58 files). Raw data
remain local under `results/physical-calibration`. The first adapter attempt
stopped before fitting because raw files have 49 columns, not 48. The source
plotting scripts use exactly 16 voltage, 16 current and 16 temperature columns;
the final auxiliary channel has no verified interpretation. Corrected parsing
preserves that raw channel and signed near-zero current measurements.

`thermal-fit-v2/report.json` inventories 39 experiments and evaluates all 26
long-step experiments against the frozen protocol. Natural convection has only
**1/4** eligible calibration cases (`one`); forced convection has **2/4**
(`one`, `line_1`). The preregistered minimum is 3. Thus neither group was fitted.
No thresholds, case membership, offsets or sensor permutations were changed.

The raw traces do not all contain 30 minutes at the high-power setting:
12/13 natural-convection runs end their high-power interval after 44.2--387.3 s,
with the last powered sample's maximum sensor temperature 99.5--99.8 C.
The forced-convection `sixteen` case stops at 1159.3 s and 99.7 C. This is
**consistent with a roughly 100 C protection cutoff**, not a verified decoded
alarm. No measured equilibrium above that cutoff is available. Natural
convection `one` runs 1800 s; the other 12 fan cases run 1800 s.

The causal implication follows from `P = dU/dt + Q_out`: a rising temperature
means stored energy is still changing. Substituting the end temperature into a
steady equation silently assigns that stored energy to a fictitious heat loss.
Neither a paper's generic experiment description nor a 100 C endpoint makes
that substitution valid. Short-run high-power cases require a transient model
and their actual input history. Even flat finite windows do not prove global
equilibrium without a bound on unobserved slow modes.

The reviewer confirmed the 17-node positive-conductance interpretation but
emphasized that its common bath forces all heat through one node. Consequently
fitted conductances cannot be interpreted as silicon k, TIM resistance or
convection h, or transferred between cooling fixtures. Ambient is one scalar
per run: ambient drift cannot be independently screened from these files.
Sensitivity rank without a measured covariance is a conditional numerical
diagnostic, not an experimental confidence interval.

Pad work uses four actual CoolCAD measured n/p high-voltage primitive files.
The 108 curve/scenario comparison is a separate conditional diagnostic in
progress at this admission milestone. The measurement temperature, lot and
complete layout/probe contract remain missing; no PDK parameters are changed.

Validation at this milestone: 117 unit tests passed, including analytic uniform
heating/rank deficiency, spatial excitation identifiability, conservative
network ledger, signed/name-based MDM parsing, and negative controls. The
two-chiplet CLI remains 3 W, reference peak 34.1886068 C, thermal uncalibrated,
timing not_run. Existing production solvers and settings are unchanged.

References:
- https://zenodo.org/records/3345878 (Terraneo, Leva, Fornaciari, CC-BY dataset v2)
- https://re.public.polimi.it/handle/11311/1099255 (author manuscript, pp. 4--9)
- https://github.com/google/skywater-pdk-sky130-raw-data/tree/1f7214f2f81a0629303947a07e1ec00a28ae8a33

Reproduce (PowerShell, from repository root):

```powershell
. ./tools/windows_env.ps1
$env:PYTHONUTF8='1'
python tools/calibrate_measured_thermal.py --output results/new-ttc-admission
python tools/compare_measured_pad.py --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe --output results/new-measured-pad
```

The first command deliberately produces `not_fitted` for this frozen steady
protocol. That status must not be rewritten as calibration success.
