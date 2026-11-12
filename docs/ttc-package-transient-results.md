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
