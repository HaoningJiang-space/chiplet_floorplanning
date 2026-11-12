# Fixed-parameter TTC spatial falsification: failed improvement and mesh gates

Local-only session, start `7cc3371`, source/implementation milestone `988f9a8`.
Successful fetch found remote unchanged at `c124aa9`. No push, no remote CI.
The preceding goal turn made progress; this turn adds independent spatial and
continuum evidence. The full ten-metric goal remains active and incomplete.

## Declared experiment, including the unsuccessful result

See `ttc-spatial-plan.md` and its frozen original copy in the result directory.
The new finite-volume network resolves 32 heater rectangles and 16 sensor
positions in bottom active Si / bulk Si / silicone-pad layers. Source parser
and die files at author commit `1ce8c0a` establish the layer order; their hashes
are in `tools/ttc-layer-order.lock.json`. They remain ignored third-party files.

The bath is spatially uniform but dynamic, with **unchanged** G_a/C_b from the
previous end-observation fit. Source-fitted Si/pad properties are unchanged.
This is a hybrid diagnostic, not a reproduction of the full author heatsink.
No copper spreading, fin flow, new fit or time shift is introduced. Changing
internal representation also changes internal capacity and transfer function,
so any improvement could not be attributed to geometry alone.

Primary grid: maximum x/y width 500 um with exact heater edges, 1/2/2 depth
cells in active/bulk/pad, 3,361 nodes. All modes retained, analytical 0.1 s
interval propagation, native unsmoothed residuals. All 26 records are retained.
Four calibration and nine held-out labels per group are inherited, not blind
validation. The matched baseline uses the same conditional initialization:
first-second mean-power stationary internal field plus a common offset matching
the first measured sensor mean. That offset produces a **nonstationary** bath
state; no whole-system steady-state claim is made. A uniform-temperature initial
field is a separately reported sensitivity control for both models.

| Held-out group | Model | Total RMSE K | Common RMSE K | Spatial RMSE K | Max abs K |
|---|---|---:|---:|---:|---:|
| Natural | Matched 17-node baseline | 1.63281 | 1.55836 | 0.48743 | 18.13126 |
| Natural | Source geometry / uniform bath | 2.31263 | 2.19103 | 0.74002 | 20.61247 |
| Fan | Matched 17-node baseline | 2.75711 | 2.60607 | 0.90003 | 13.28660 |
| Fan | Source geometry / uniform bath | 1.90982 | 1.24410 | 1.44901 | 14.95766 |

Only **1/9 held-out patterns improves in each group**, against the frozen
requirement of at least 7/9 and a 20% aggregate spatial RMSE reduction in each
group. Spatial RMSE instead increases about 52% / 61%. Fan total RMSE improves
because the common component falls; it is not evidence of better spatial
prediction. Initial-field controls preserve this spatial result: after the
first 60 seconds, spatial RMSE is effectively independent of those two initial
choices. Common-temperature errors remain initialization-sensitive.

The experiment also **fails its numerical convergence screen**:

| Control, maximum over 13 nominal source patterns | Natural K | Fan K |
|---|---:|---:|
| Primary to 250 um xy refinement, steady | 0.52005 | 0.52278 |
| Primary to 1/4/4 z refinement, steady | 0.50886 | 0.52478 |
| Primary to xy refinement, 1 s switch experiment | 0.52848 | 0.52781 |
| Primary to z refinement, 1 s switch experiment | 0.51404 | 0.52734 |
| Backward-Euler 0.005 to 0.0025 s change | 0.09722 | 0.08938 |

The 0.1 K threshold and additional 10%-of-improvement requirement stay unchanged.
These results do not falsify spatial heat conduction in the hardware. They reject
admission of this particular frozen numerical/model configuration as improved
physical prediction. High-power steady controls are mathematical comparisons,
not claims that the protected TTC can sustain those temperatures.

## Independent continuum reference after FV nonconvergence

The finite-volume failure motivates a **separate** continuum solution, without
changing the frozen primary prediction. For the same rectangular, laterally
insulated, constant-property layers, expand areal power and temperature in
`cos(n*pi*x/L) cos(m*pi*y/L)`, with `q=pi*sqrt(n²+m²)/L`. Heater coefficients
are analytic rectangle integrals, including their half-power allocations.
Sensor observations are point values at the actual x/y coordinate and active
mid-depth, consistent with the active layer node's z location.

For a passive layer with thickness d, conductivity k and top admittance Y,
the input admittance is

`Y_in = k*q*(Y + k*q*tanh(q*d))/(k*q + Y*tanh(q*d))`.

The pad's top is the uniform bath, so nonzero lateral modes see a zero-temperature
Dirichlet condition: `Y_pad = k_pad*q/tanh(q*d_pad)`.
Propagate through the bulk to obtain Y_load.
For active thickness a and uniform volumetric generation, the active midpoint
temperature per modal areal power is

`Z(q) = [1 - cosh(q*a/2)/(cosh(q*a) + k_si*q/Y_load*sinh(q*a))] / (k_si*a*q²)`.

The exact zero mode is
`Z(0)=3*a/(8*k_si) + d_bulk/k_si + d_pad/k_pad`.
Add the uniform bath's steady rise `P_total/G_a` only to that common component.
The factor 3/8 follows the quadratic active-layer profile with an insulated
bottom, rather than assuming a source at a single cell center.

Independent verification uses a **six-state, three-segment boundary-value ODE**
with temperature and flux continuity, over lateral q from 0 to 300,000 m^-1,
plus the uniform-source zero-mode limit. It does not reuse the admittance
recursion. FVM's one-dimensional quadratic limit converges with the expected
fourfold error reduction when depth-cell count doubles. Reciprocal conductance
also matches an independently assembled uniform-grid Kronecker Laplacian.

Series 16/32/64/128/256 initially failed the 0.01 K successive-change screen;
`ttc-spectral-v1` preserves that failure. Extending only the numerical series
to 512/1024 gives maximum changes of 0.0105384 / **0.0012910 K**. This is a
convergence diagnostic, not a rigorous remainder bound or hardware accuracy.

| FV versus 1024-mode steady continuum, all 13 nominal patterns | Natural K | Fan K |
|---|---:|---:|
| Coarse, 1,106 nodes | 3.05593 | 3.06945 |
| Primary, 3,361 nodes | 1.67283 | 1.69558 |
| xy-refined, 11,026 nodes | 1.17325 | 1.19692 |
| z-refined, 6,049 nodes | 1.16929 | 1.18105 |

Refining only one direction leaves other discretization errors. The next
numerical step must inspect sensor-coordinate errors and coupled x/y/z
refinement or a controlled continuum reduction before using the transient FV
model for physical ranking. Conservation alone cannot close this gap.

## Secondary approximate-DC spatial diagnostic

This post-primary diagnostic was declared in an addendum before its calculation;
it is exploratory, not a retroactive new primary test. Take the 9 s window
ending 1 s before each main power interval ends. Compare mean measured sensor
differences to the continuous steady prediction under mean measured power.
All 26 cases pass the declared <=2% channel-vector power drift and <=0.1 K
spatial-temperature drift screens. Small drift is not proof of exact steady
state. The conservative internal relaxation bound
`tau <= 4*H²*Cv_max/(pi²*k_min)` is 0.359 / 0.256 s for the stated zero-bath
internal stack, and does not describe the complete measured fixture.

For `Q = I - 11^T/16`, `Q*T_sensor` removes the uniform bath temperature. The
same-height sensors and homogeneous lateral materials make this spatial
observation independent of G_a and C_b under the stated uniform bath model.
The implementation verifies bath-resistance cancellation. No ambient or bath
fit is needed for this contrast, but the **uniform-bath assumption remains**.

| Held-out group | Frozen reduced static RMSE K | Continuum spatial RMSE K | Improved patterns |
|---|---:|---:|---:|
| Natural | 1.18430 | 1.52494 | 3/9 |
| Fan | 0.92197 | 1.15427 | 4/9 |

Thus simply resolving the internal geometry with the source materials and a
uniform bath does not improve this measured spatial contrast either. Material,
sensor, contact and spatial boundary assumptions remain plausible explanations;
the evidence does not uniquely identify copper spreading as the cause.

## Validation, review and continuation

135 tests pass and the standard two-chiplet CLI runs: 3 W, 34.1886068 C reference
peak, production thermal uncalibrated, timing not_run. Maximum normalized
whole-run energy residual for spatial predictions is 7.63e-10; maximum absolute
per-interval or per-layer residual is below 2.2e-9 J. Numerical screens remain
necessary, not sufficient. No production module changed.

Three completed ChatGPT reviews, via the user's authorized
`codex-chatgpt-skill`, covered design, frozen gates and negative-result
interpretation in the existing [review conversation](https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865).
Applied advice includes explicit dynamic bath, matched conditional initial
states, fixed thresholds, and separation of continuum/model and numerical
error. We corrected the review's initial suggestion that the offset state must
remain globally steady; the follow-up accepted the nonstationary conditional
initial-state interpretation. Model review is advisory, not an independent run.

Next actions: locate and close the FV/continuum sensor error first; compare the
same source geometry under uniform versus source-sized copper base/fin boundary,
without fitting to these outcomes. Air exchange and contact assumptions must
remain traceable. Use the same DC windows as a paired mechanism diagnostic;
independent hardware data are still required for generalization. The remaining
Pad/PEX, measured channel and multi-lane/timing/optimization gates are unchanged.

Reproduce locally in fresh output directories:

```powershell
. ./tools/windows_env.ps1
python tools/audit_ttc_spatial.py --output results/physical-calibration/ttc-spatial-fresh
python tools/audit_ttc_spectral.py --spatial results/physical-calibration/ttc-spatial-fresh --output results/physical-calibration/ttc-spectral-fresh
python tools/audit_ttc_spatial_dc.py --output results/physical-calibration/ttc-spatial-dc-fresh
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/physical-calibration/ttc-spatial-cli-fresh
```

Inputs, source/code hashes, primary and secondary results remain separately
frozen in the ignored local result folders. The tracked compact evidence index
is `docs/evidence/local-ttc-spatial.json`. Failed experiments are preserved.
