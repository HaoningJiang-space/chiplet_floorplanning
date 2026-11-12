# Preserved reduction failure and numerical enrichment

The `b7db931` transient experiment completed all four level-0 package models.
Every one failed the frozen reduction screen. The local process was deliberately
terminated after beginning the first level-1 snapshot, before spending more time
on that inadequate construction. `termination.json` retains this distinction
from a completed experiment. Original waveforms and numerical controls remain.

For natural cooling / cropped pad, the finest original 161-state reduction has
0.237 K maximum withheld-frequency error, 0.0364 K pulse error against the
independent full-network Richardson reference, and a -0.000586 K minimum positive
step response. Middle-to-fine native trace differences reach 0.457 K. Stability,
DC preservation and heat conservation did not guarantee point-sensor accuracy
or positivity. None of these failed models is physically qualified.

Use the same full G, C, B, H, physical coefficients, measured cases, initial
conditions and thresholds. Enrich only numerical real-shift sampling to cover
fast diffusion as well as package relaxation. Keep the original eight shifts as
order 0; orders 1 and 2 add half- and quarter-decade sampling from 1e-3 through
1e7 1/s, with the DC snapshot and mandatory input/body directions unchanged.
The exact arrays are frozen in `tools/ttc-transient-enrichment.json`. This is not
a fit to measured temperatures. The shift range includes time scales faster
than the 1 microsecond numerical step-response screen; it does not prove a
uniform frequency/time error bound.

The first numerical-only control, natural cooling / cropped pad / level 0,
reduces withheld-frequency error to 0.00628 K (half-decade) and 0.0000286 K
(quarter-decade). Both sampled step screens pass. Pulse errors are 0.000683 K
and 0.000302 K, respectively. These values qualify this numerical control only;
the other geometries, mesh level, native trace order changes and heat ledgers
must still pass separately.

Identical full-network BE controls may be reused after original source hashes,
physical inputs and complete assembled-geometry audits match. Save the reused
raw controls and their hashes in the new run. Level-1 controls are computed
afresh. The earlier steady continuum correction is never applied to dynamics.

Reproduction (all local):

```
python tools/audit_ttc_reduction_enrichment.py --output results/physical-calibration/ttc-reduction-enrichment-new
python tools/audit_ttc_package_transient.py --shifts-file tools/ttc-transient-enrichment.json --prior-controls results/physical-calibration/ttc-package-transient-v1 --output results/physical-calibration/ttc-package-transient-v2
```

User-directed review cadence: complete a coherent major goal/stage before
requesting one comprehensive ChatGPT review of its Git history, assumptions,
failed controls and results. Keep local commits timely throughout; advisory
review does not certify the physics. Do not send each small revision for review.
