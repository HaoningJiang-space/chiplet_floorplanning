# Public measurement calibration, preregistered 2026-11-11

Base: local `0aec6ca`, successful origin fetch, `origin/main=c124aa9`,
ahead 5 / behind 0. Local execution and commits only. No production parameter
changes or physical admission based on these experiments.

## Evidence and physical question

Use Terraneo, Leva and Fornaciari, *An Open-hardware Platform for MPSoC Thermal
Modeling* (2019), Zenodo **3345878 version 2**, DOI 10.5281/zenodo.3345878.
The archive SHA256 is
`3fc86c8d59a3b1cff1f45d1caa7eb21e56be39e22d75f24fb6ba2557b92111b0`.
The hardware is TTV-1202, a 10.23 mm square silicon TTC, flip-chip BGA,
16 heater/diode cells, copper HS483-ND heatsink and P14752-ND fan.
This is a measured single-die test vehicle, **not our chiplet package**.

Start from energy conservation:

`rho*c*dT/dt = div(k grad(T)) + q`, and
`integral(q) = dU/dt + sum(boundary heat flows)`.

The observed quantity is the calibrated diode temperature `H[T]`, not a mesh
maximum. Sensor bias, spatial averaging, lag and self-heating remain potential
model discrepancy. Kelvin voltage readback and current measurements permit
`mean(V_i*I_i)`; do not substitute nominal setpoints or `mean(V_i)*mean(I_i)`.
The paper gives 0.1 K, 6 mV, 0.5 mA resolution and a 0.8% calibration-reference
multimeter, not a complete propagated uncertainty/covariance budget. Never
treat resolution as absolute accuracy. Ambient is one CP11 reading per run.
V2 corrects two sensor rotations, calibration shifts up to 1.5 K and some poor
contacts. No new rotation or per-case temperature offsets may be fitted.

## Frozen thermal protocol (before loading temperature arrays)

- Inventory/hash all 39 raw files. `chip/` is **1 kHz fast dynamics**, not bare
  chip steady data. Inventory it only; do not fit heat capacity this round.
- `heatsink/` and `heatsink_with_fan/` are separate **10 Hz** long-step groups.
  Fit each cooling condition separately.
- Calibration patterns: `one`, `four`, `sixteen`, `line_1` (4 per group).
  Nine other complete experiments per group are held out. No time-sample split.
- Find the longest contiguous high-power interval using total measured power
  above the midpoint between nominal baseline 3.2 W and the pattern total.
  Use its final 60 s, require at least 120 s of continuous activation. Keep the
  full raw trace and the exact selected indexes. No temperature-based window
  search. For each run report maximum absolute least-squares temperature slope,
  first/last 20 s mean difference, and relative power drift over those windows.
- Predeclared quasi-steady screens: slope <=0.002 K/s, temperature-window drift
  <=0.25 K, total-power drift <=2%. Failing calibration cases are not fitted;
  all cases and failures remain in results. Held-out failures are reported as
  endpoint diagnostics, not validated steady-state measurements. If fewer than
  3 calibration cases survive, do not fit the group.
- Check measured power pattern against the named row-major 4x4 pattern;
  report relative RMS mismatch, do not reorder sensors to improve fit.

Use a deliberately limited, passive 17-node reduced model: a 4x4 nearest-neighbor
grid with common edge conductance `g_xy`, each cell connected by `g_z` to one
common bath node, and bath connected to measured ambient by `g_a` (all W/K).
Let `L` be the unit grid Laplacian. At steady state:

`theta = solve(g_xy*L + g_z*I, P) + sum(P)/g_a`.

This follows directly by eliminating the bath temperature from the conservative
network. The single bath, uniform couplings and identity sensor observation are
testable reduction assumptions, not recovered geometry. Board paths, contact,
radiation and convection are not separately observable here. In particular,
`g_z` is not a measured TIM conductance, and `g_a` is not convection `h*A`.

Fit only 3 positive equivalent conductances by unweighted least squares in K,
equal weights to each cell/run. Minimize in log conductances, numerical bounds
`g_xy,g_z in [1e-4,100]`, `g_a in [1e-3,100]` W/K; 4 fixed starting triples
`(0.05,0.1,1)`, `(1,1,1)`, `(0.01,1,0.1)`, `(1,0.01,10)`.
Report bound hits and multistart spread; bounds are computational, not material
priors. Report held-out per-cell RMSE, bias and maximum error in K, measured
sensor peak separately from predicted sensor peak. No physical pass/fail error
threshold is inferred without a complete measurement uncertainty budget.

Inspect singular values of the log-parameter sensitivity matrix (relative rank
cutoff 1e-6), and demonstrate the exact uniform-source rank deficiency. A full
rank under localized heating establishes only local identifiability of this
3-parameter reduced model. Separating additional series contact/convection
resistances gives identical sensitivity columns: demonstrate this negative
control, not a unique material estimate. Retain prediction residual maps.
Audit numerical conservation `G*theta=P`, symmetry, signs, positive definiteness,
and bath heat `g_a*theta_bath=sum(P)` independently of fit error.

## Frozen Pad primitive diagnostic

Source: Google's `skywater-pdk-sky130-raw-data`, commit
`1f7214f2f81a0629303947a07e1ec00a28ae8a33`, CoolCAD measurements of SkyWater's
manufacturing test tile (Apache-2.0). Select the four IDVD/IDVG files of n/p
`g5v0d10v5`, W=7 um, L=0.5 um, m=1 (tiles 8389_7_8 and 8395_8_7).
These are actual measured primitives relevant to the Pad library, not measured
complete GPIO/PEX or measured package channels. The selected MDM headers lack
measurement temperature, lot and a complete probe/uncertainty contract.

Strictly parse header-defined sweep variables and each DB column by name,
including differing ID/IG column order. Preserve signed currents and body bias.
Evaluate the existing hash-locked TT models **without fitting**, at assumed
20/25/30 C (sensitivity scenarios, not a measured temperature uncertainty range).
All 36 measured bias curves, 3 scenarios: 108 curve/scenario comparisons.
Use exact sweep coordinates; no extrapolation. Report ID RMSE/max error in A,
and RMS error normalized by each curve's measured peak (floor 1 nA). Report
on-state errors separately for |ID|>=10 uA to avoid leakage/noise blowups.
Check model four-terminal KCL and total port DC power; inferred source current
from measured ID/IG/IB is not an independent measured KCL test.

Raw measured readout has been seen only to inspect schema; no model comparison
or fitting has been performed. No learned parameters, no selected fit threshold,
no physical validation claim: unknown measurement temperature remains a blocker.

## Reviewer and admission

ChatGPT review in the existing research chat requires explicit measurement
operators, calibration/validation separation and parameter identifiability.
Apply those recommendations; reviewer suggestions are not measurement evidence.
Real GPIO delays, package electromagnetic parameters, and target chiplet thermal
boundaries remain unqualified. Do not enable thermal timing optimization.

### Adapter correction before any fitted result

The first load attempt (`thermal-fit-v1`) failed at the schema check: the raw
files have **49** columns, while source plotting scripts explicitly consume
only 1..48 (V, I, T). Column 49 is an undocumented auxiliary channel, retained
in the immutable source but not interpreted. Signed near-zero current readout
also exists when voltage is zero; preserve it without clipping. Use only the
16 defined temperature columns. This changes no window, split or fit rule.
The corrected execution uses `thermal-fit-v2`; the failed frozen inputs remain.
