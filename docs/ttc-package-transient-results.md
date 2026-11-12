# Package transient checkpoint: reduction verified, mesh still open

The local `b387f20` experiment completes all four level-0 combinations of natural
or fan cooling and cropped (C) or full 27 mm (P) contact pad. Each cooling group
uses the same 13 native measured records, two conditional initial states and
three nested reduction orders. Level 1 is still running. The separate full
steady package study has reached its 4.6-million-node level-3 C network.

The original `b7db931` reduction failed and was preserved before enrichment;
see `ttc-reduction-enrichment.md`. No material, contact, air or observation
parameter was fitted during this correction. Original acceptance thresholds
were retained. Numerical-only enrichment restores the required accuracy.

| Level-0 model | Reduced states | Max withheld frequency error / K | Full BE extrapolate pulse error / K | Max middle-to-fine native change / K |
|---|---:|---:|---:|---:|
| Natural C | 474 | 0.0000286 | 0.000302 | 0.000677 |
| Natural P | 478 | 0.0000356 | 0.000279 | 0.000905 |
| Fan C | 476 | 0.0000421 | 0.000294 | 0.000964 |
| Fan P | 482 | 0.0000678 | 0.000232 | 0.001512 |

All four finest reductions pass the declared frequency, pulse, sampled positive
step, native-trace order and per-body heat-ledger screens. The largest normalized
whole-record heat imbalance is 1.42e-9. Congruence preserves stability and source
port passivity; sampled point-sensor positivity is a separate numerical check,
not a proof for every possible waveform. Full BE's own time refinement and
heat ledger are retained. Reused level-0 BE reference arrays match frozen model
sources, physical inputs and assembled geometry; the new run records hashes.

## First-principles finding to test on finer meshes

The balance is `input power = total body storage rate + heat removed to air`.
For natural C in the checkboard record's original 9 s diagnostic window:

- Measured electrical input is 25.139 W.
- The model stores 17.085 W and removes 8.054 W to the ambient reservoir.
- The largest sensor-difference change from raw steady to raw transient is
  only 0.00188 K in this window.

This supports a distinction within this coarse model: substantial slow package
storage can coexist with a nearly settled spatial sensor contrast. Copper
storage mostly changes the common temperature in these windows, rather than
explaining the observed spatial residual. It is not evidence that the physical
device is in global equilibrium. Stored body heat is predicted, not independently
measured. Across all 13 windows, maximum dynamic-minus-static spatial differences
are 0.00432/0.00376 K for natural C/P and 0.000396/0.000341 K for fan C/P.
The approximately 47 W sixteen cases are outside the source's <40 W boundary
domain and remain labeled calibration cases; the checkboard example is in domain.

The two initial-state assumptions produce native-temperature differences up to
1.35–1.71 K. Their difference is a sensitivity diagnostic, not a measured
uncertainty distribution or bound on unknown initial body temperatures.

## Measured errors remain material

Each entry below uses all native unsmoothed samples in the nine existing
domain-eligible held-out records per cooling group, weighted by record duration.
Common and demeaned spatial residuals are orthogonal, so their squared RMSEs
sum to raw squared RMSE. The holdouts are reused, not new blind measurements.

| Conditional-gradient initial state | Common RMSE / K | Spatial RMSE / K | Raw RMSE / K |
|---|---:|---:|---:|
| Natural C | 1.5319 | 0.5219 | 1.6184 |
| Natural P | 1.3850 | 0.5434 | 1.4878 |
| Fan C | 0.8081 | 0.9635 | 1.2576 |
| Fan P | 0.9846 | 1.0128 | 1.4125 |

These are whole-record scores, including preactivation and cooldown. They must
not be compared directly to DC-window RMSE or the source paper's smoothed MAE.
The alternate uniform initial state is retained in the machine-readable evidence.
No steady continuum correction is applied to any transient prediction.

## Remaining work and review cadence

The first completed level-1 result (natural C) passes the same-grid reduction
screen: maximum withheld-frequency error 0.0002772 K, full-BE pulse discrepancy
0.0003151 K and middle-to-fine native-trace change 0.0011307 K. Nevertheless,
changing from mesh level 0 to 1 changes conditional-gradient native temperatures
by up to 0.98383 K, with demeaned spatial change up to 0.94600 K. This is observed
grid dependence, not a physical error bound. In the checkboard window, predicted
storage remains 17.0849 W and dynamic-minus-static spatial contrast is 0.001947 K.
The storage observation persists, while spatial numerical accuracy remains open.

A retrospective localization now compares all 13 natural-C records on identical
power and observation arrays, after verifying both meshes' saved waveform hashes.
The largest conditional-gradient change is `hotspot_2`, sensor index 0, native
sample index 600 (raw index 18106): 0.983833 K = 0.037831 K common + 0.946002 K
spatial. The model interval ends at 60.1 s since initialization; this is the
declared 0.1 s integration convention, not verified logger hardware phase.
The simultaneous input is 11.3961 W, within the declared source power domain.
The uniform initial-state variant peaks at the same sample and sensor, 0.994057 K;
its spatial component is 0.946001 K. Initial-state choice has not removed this
observed local grid dependence.

Across the nine existing eligible held-out records, duration-weighted two-grid
RMSE is 0.087145 K: common 0.025375 K and spatial 0.083369 K. Their squared values
add, with maximum per-record identity residual 3.5e-18 K^2. Spatial changes account
for 91.52% of the mesh-change MSE (89.78% with uniform initialization). This is
**grid-change decomposition**, not measured-residual attribution or a probability
distribution. Across all 13 records the corresponding fraction is 90.31%.

In the fixed `hotspot_2` diagnostic window, the maximum dynamic spatial grid
change is 0.771294 K, versus 0.771277 K for the static solution. The difference
between these two grid-change vectors is at most 1.94e-5 K. For `checkboard`, the
corresponding values are 0.205781/0.205850 K and 7.09e-5 K. Within this model and
these windows, transient copper storage does not remove the local spatial
discretization sensitivity. This does not isolate which geometric layer or
observation operator causes it, nor justify tuning contact/convection parameters.

Reproduce the localization without another full-network solve:

```
python tools/audit_ttc_mesh_change.py --input results/physical-calibration/ttc-package-transient-v2 --output PATH_TO_OUTPUTS
```

The report preserves both initial states, all cases, peak coordinates and source
hashes. Tracked evidence: `evidence/local-ttc-mesh-heatsink-C.json`. It does not
provide a two-grid error bound or establish spatial convergence.

Complete level-1 full-network controls and native simulations; compare identical
power/observation arrays across grids, and preserve any failures. Two grids do
not establish an error bound. Continue the independent level-3 steady package
boundary contrast. Initial copper/fin temperature, logger phase/averaging,
contact material, convection/air warming and radiation still need evidence.
No real chiplet thermal boundary, electrical Pad, thermal-timing interface or
optimization claim is qualified by this checkpoint.

The user requested goal-level review: after completing a coherent major stage,
send its full relevant Git history, tests, unsuccessful controls and evidence to
ChatGPT together. No micro-review was requested for these corrective commits.

The immutable local checkpoint is
`results/physical-calibration/ttc-package-transient-v2/checkpoint-level0.json`.
Compact tracked evidence is `evidence/local-ttc-package-transient-level0.json`.
The renderer verifies waveform hashes and keeps numerical, mesh and physical
qualification statuses separate:

```
python tools/render_ttc_package_transient.py --input results/physical-calibration/ttc-package-transient-v2 --output PATH_TO_OUTPUTS
```
