# Explicit package boundary: first completed checkpoints

Implementation/frozen protocol commit: `506f314`. Starting checkout was
`a87e529`; GitHub fetch succeeded and origin remained `c124aa9`. All work is
local, without a push or remote job. This document records completed levels
0 and 1; levels 2 and 3 are still being calculated. Do not read it as a final
convergence result. The active run is `ttc-package-boundary-v1` under
`results/physical-calibration/`.

The complete coupled FV network now represents the die, actual pad footprint,
copper base and 23 fins. Bodies share a conforming Cartesian partition so
interface cell centers align with the normal. Each interface includes both
half-cell conduction resistances; opposing heat flows use one conductance.
The initially considered nonmatching two-point approximation was discarded
before implementation, since conservation alone would not ensure consistency.

Source provenance is pinned by `tools/ttc-package-boundary.lock.json` and the
earlier TTC lock. Geometry and fitted parameters come from the public author
[HS483 fixture](https://github.com/esl-epfl/3d-ice/blob/1ce8c0ad00b96acae52fc83508c61e3b4ad612df/heatsink_plugin/heatsinks/HS483/HS483.mo)
and [boundary equations](https://github.com/esl-epfl/3d-ice/blob/1ce8c0ad00b96acae52fc83508c61e3b4ad612df/heatsink_plugin/common/HeatsinkBlocks.mo).
The independent implementation is not a transcription of the upstream solver.
Natural h=2.8 W/m2K and the source fan correlation are retained without fitting.
Fin position is inferred from equal base strips, not measured independently.
The two broad fin sides exchange with fixed-temperature air; omitted radiation,
other exposed faces and air-temperature evolution remain model assumptions.

## What passed and what did not

146 tests passed, including new constant/affine interface fields, exact layered
resistance, insulated-tip fin refinement, source-port reciprocity, AMG versus
direct solve, and the uniform-boundary fixture versus the separated solver on
the same custom axes. The two-chiplet CLI retains 3 W and 34.188607 C, with
thermal uncalibrated and timing not run. Production modules are unchanged.

Level 1 has 24,010 nodes in U, 100,366 in C and 111,398 in P. On unit source
controls its maximum local equation residual is below `1.6e-13 W`, total heat
balance error below `1.7e-11 W`, and block balance error below `8.7e-12 W`.
The uniform fixture matches the independent same-grid solver within
`2.7e-11 K` on the 13 nominal patterns. These are algebra/conservation checks.

**The boundary-effect convergence gates have not passed.** The first refinement
still changes the demeaned sensor response by:

| Material group | C-U maximum change (K) | P-C maximum change (K) |
|---|---:|---:|
| Natural | 0.154594 | 0.237654 |
| Fan | 0.182139 | 0.177878 |

All exceed the frozen 0.02 K threshold. U is the uniform top boundary; C adds
copper/fins with a die-sized pad; P expands the pad to its source 27 mm square.
C-U changes both the physical boundary and copper structure; it is not a pure
geometry attribution. P-C isolates pad extent within this declared model.

For transparency, the current numerical-correction estimate gives these
exploratory held-out sensor-difference RMSEs:

| Group | U continuum (K) | C corrected (K) | P corrected (K) |
|---|---:|---:|---:|
| Natural | 1.524935 | 1.121920 | 1.188925 |
| Fan | 1.154269 | 0.685919 | 0.739858 |

At this checkpoint C/P improve all 9 held-out patterns relative to U, and the
20% reduction screen is met. **This does not pass the overall experiment:**
numerical convergence is still missing and the DC comparison has the physical
limitation below. Raw FV predictions are also saved and shown in the report.
The correction `R*=R_U_continuum+(R_package_FV-R_U_FV)` is not a true solution
or a proven error bound. Its boundary difference must independently converge.
The previous coarse transient experiment and its failure remain unchanged.

## A material physical finding: common temperature is still changing

From `C dT/dt + G T = B P` with positive C and symmetric positive definite G,
the constant-vector generalized Rayleigh quotient yields
`lambda_min <= sum(boundary conductance)/sum(capacity)` and therefore
`tau_slowest >= sum(capacity)/sum(boundary conductance)`.
It is a lower bound on the slowest model time constant, not a convergence time,
an upper bound, or proof that the mode is significantly excited at a sensor.

| Group / pad | Total heat capacity (J/K) | Boundary conductance (W/K) | Slowest-time lower bound (s) |
|---|---:|---:|---:|
| Natural / cropped | 81.020144 | 0.148377 | 546.041 |
| Natural / full | 84.140856 | 0.148377 | 567.073 |
| Fan / cropped | 81.020144 | 1.175599 | 68.918 |
| Fan / full | 84.140856 | 1.175599 | 71.573 |

Most natural-cooling diagnostic windows start only 34–377 s after the main
power activation (`one` starts at 1790 s). Their spatial drift was small in the
earlier 9-second screen, but the measured **sensor mean still rises**: about
0.00247 K/s for `one`, 0.08216 for `four`, 0.24623 for `nine`, and 0.53596 for
`sixteen`; the held-out hotspot cases are about 0.042–0.053 K/s. These slopes
are differences of two half-window means separated by 4.5 s, not fitted model
parameters. Fan cases have smaller slopes, mostly about -0.0047 to 0.0028 K/s,
with the out-of-domain `sixteen` at 0.01472 K/s.

Thus stable sensor **differences** are not evidence of stable whole-system
temperature. The earlier uniform bath could eliminate a common offset from
the DC diagnostic. A spatially resolved copper/fin body also has changing
internal heat flows and stored energy. The next physical gate is a fixed-
parameter transient check on this same network, including storage and fin heat
loss. Even a completed steady refinement cannot close that gate.

## Count correction and review

The frozen design text and initial ChatGPT prompt mistakenly anticipated 8
domain-eligible held-out patterns after excluding `sixteen`. The authoritative
labels put `sixteen` in **calibration**, so each group still has 9 eligible
held-out patterns. The executable always uses the saved labels and actual
power <40 W and did not implement an 8-case denominator. No split, threshold
or case was changed. This correction is recorded separately so the frozen
protocol hash remains valid during the long run. U-versus-itself tiny floating
differences are not interpreted as improved patterns.

Three completed ChatGPT review rounds covered the design, conforming-interface
correction, and time-constant bound. Applied corrections include matching grids,
explicit raw/corrected comparisons, no unique boundary attribution, and the
distinction between a slow-mode bound and measured transient behavior. Review
did not execute the calculations and is not independent physical validation.

## Reproduction and continuation

```powershell
. ./tools/windows_env.ps1
$env:PYTHONUTF8='1'
python tools/audit_ttc_package_boundary.py --output results/physical-calibration/package-fresh
python tools/render_ttc_package_boundary.py --input results/physical-calibration/package-fresh --output <report-directory>
```

The running command computes all four planned levels sequentially. A completed
unit-source transfer has a hash receipt. If the process actually terminates,
`--resume` verifies frozen code/input hashes and reuses complete transfers.
Do not launch a second job merely because observation times out or a checkpoint
has not appeared yet. The overall ten-metric research goal remains active.
