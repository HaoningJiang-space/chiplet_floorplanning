# TTC source geometry and observation audit

Local-only experiment, 2026-11-11. Start `2a24b89`; source/plan/numerical
milestone `78c7958`. Successful start and milestone fetches found origin still
at `c124aa982eb97f49a7f4be907554c94436ace2d2`. No push or remote CI.

## Evidence recovered from the original author

Pinned [3D-ICE 3.0 source](https://github.com/esl-epfl/3d-ice/tree/1ce8c0ad00b96acae52fc83508c61e3b4ad612df)
contains `test/validation-scripts.tar.gz`, SHA256
`1be7dc2fa9f26e05c7771835521814becb3d1253d8293aa056ccb9c1250f088d`.
`tools/ttc-upstream.lock.json` pins 20 files (9 direct files, 11 archive members).
GPL-licensed source stays in ignored local results; no upstream script is run
and no residual-smoothing implementation is copied into this project.

`download.sh` references the exact [Zenodo 3345878](https://zenodo.org/records/3345878)
measurement archive already used, and deletes both `sixteen` runs. `HS483.mo`
limits its fitted heatsink model to less than 40 W; the excluded patterns are
about 48 W. `genpower-batch.sce` writes each row's V*I. The validation stacks use
0.01 s solver steps, 0.1 s input slots and slot output. `thermal_data.c` advances
time after solving; the emulator writes the completed-slot temperature.
`compare-batch.sce` subtracts it from the measured temperature at the same row.
This establishes **interval-end evaluation**, not hardware sampling semantics.

The comparison script also replaces selected residual spikes with neighbor
averages and then reports mean absolute and maximum error. Our primary output
uses unsmoothed MAE, RMSE and maxima on all 26 runs. This audit does not reproduce
the full published 3D-ICE simulation or attribute a motive to its metric policy.
The [author paper](https://re.public.polimi.it/retrieve/handle/11311/1169759/613752/CR_early_tcad_3d.pdf)
(DOI 10.1109/TCAD.2021.3074613) explicitly documents 100 C protection cutoff.

## Geometry, storage and boundary meaning

The source geometry has a 10.240 mm square die, versus the paper's rounded
10.23 mm description. There are 16 cells, each with two 2000 x 925 um heaters,
each receiving half of its cell's power. All 32 rectangles lie inside the die,
are disjoint and preserve all 16 channel powers. Their total area is 59.2 mm².
Sensors sit at cell centers in the **150 um gap** between heater rectangles;
each sensor is paired with the correct rotated input channel. Negative controls
detect a missing half-heater and a power-index permutation despite preserved
total power.

| Source-model quantity | Value | Evidentiary meaning |
|---|---:|---|
| Bulk + active Si thickness | 610 + 15 um | Author geometry |
| Silicon conductivity | 88 W/(m K) | Author-fitted, not independent measurement |
| Silicon volumetric heat capacity | 1,635,660 J/(m³ K) | Author model property |
| Whole silicon / per-cell heat capacity | 0.1071946 / 0.00669966 J/K | Derived from source geometry and property |
| Silicone thermal-pad thickness | 500 um | Author geometry; not an electrical Pad |
| Pad conductivity, natural / fan | 14.3 / 20 W/(m K) | Fitted, includes contact effects |
| Modeled pad heat capacity | 0.524288 J/K | Source-fitted Cv; only die footprint modeled |
| Copper base / fins / total heat capacity | 34.73584 / 45.65282 / 80.38866 J/K | Derived source-model geometry/materials |

The physical pad is 27 x 27 mm, while the author models only the die footprint.
No parameter is transferred to a target chiplet package. The conditional network
Ccell is not automatically the silicon cell heat capacity; sink reduction,
contact, spatial gradients and observation convention affect fitted quantities.

Ambient values come from each dataset's `tests.txt`, which names a Rotronic CP11
sensor. They are one value per run, not a recovered ambient time series. The
undocumented 49th raw column remains uninterpreted. Firmware, hardware sampling
phase, averaging window, time-varying air temperature and sensor response are
still unavailable in the recovered sources.

## Frozen computation and results

Followed `ttc-observation-plan.md`: old parameters fixed under begin/end/exact
interval-average operators, then only source-selected **end** refitted. Same four
calibration patterns and nine held-out patterns per group, all four starts and
bounds, 1 s fitting residual grid, equal run weights. No fitted fractional lag,
no holdout-driven operator choice, no smoothing and no primary exclusions.
The previously inspected holdouts are not blind validation. The 24-run subset
is additional reporting only; both 48 W runs still enter training, so this is
not a new in-range calibration.

All operators solve `C d(theta)/dt + G theta = P`. For each mode,
`z_next = exp(-lambda dt) z + (1-exp(-lambda dt)) u/lambda`.
The average is the analytic interval integral divided by dt. Initial state
assumptions are unchanged and now explicitly interpreted as pre-interval state.
The ledger covers **all N power intervals**, including the final row.

Native 0.1 s grid, nine held-out runs/group, equal-run RMSE:

| Condition | Parameters / observation | MAE K | RMSE K | Max abs K |
|---|---|---:|---:|---:|
| Natural | Old / begin | 1.34288 | 1.63450 | 26.96146 |
| Natural | Old / end | 1.34232 | 1.62914 | 15.38199 |
| Natural | Old / average | 1.34253 | 1.63127 | 20.56390 |
| Natural | Refit / end | 1.34442 | 1.63281 | 18.13126 |
| Fan | Old / begin | 2.22930 | 2.75795 | 27.99724 |
| Fan | Old / end | 2.22912 | 2.75685 | 15.84799 |
| Fan | Old / average | 2.22904 | 2.75689 | 15.74247 |
| Fan | Refit / end | 2.22912 | 2.75711 | 13.28660 |

Native results should not be silently compared with the old 1 s RMSE numbers
(1.64491 / 2.76817). The JSON preserves both grids and a secondary native metric
excluding the first conditioned second. Removing that second does not remove
the large event errors. Natural refitting worsens its maximum relative to the
fixed-parameter end observation; this negative result is retained.

New fitted Ccell is 0.01634916 / 0.01011368 J/K, Cbath is 82.15255 / 66.69839 J/K
for natural/fan. Both four-start fits converge without a bound hit. Local log-
parameter Jacobian condition numbers are 71.67 / 207.18; this is not a global
identifiability proof or a confidence interval. The fastest mode is 29.6 / 16.7
ms, below the 100 ms observation spacing. Leaving the old capacity bound does
not identify a true material property. Different Cbath for the same sink also
does not imply that the copper's physical heat capacity changed.

Worst residuals: natural hotspot_2, sensor 0, switch-on row, +18.1313 K;
fan hotspot_3, sensor 4, switch-off row, -13.2866 K. Temporal convention has a
large event effect and a small aggregate RMSE effect. No single mechanism has
been established as the cause of those measured errors.

Post-fit diagnostic, with no new optimization: decompose every residual vector
into its 16-sensor mean plus a zero-mean spatial component. Their MSEs add exactly.

| Held-out group | Common-component RMSE K | Spatial-component RMSE K |
|---|---:|---:|
| Natural | 1.55836 | 0.48743 |
| Fan | 2.60607 | 0.90003 |

About 89–91% of MSE is common component. This is not causal attribution to
ambient or boundary conductance: initialization, sensor offsets and reduced
spatial dynamics can also contribute. Geometry refinement alone may not fix it.

## Verification, review and next falsifiable question

125 unit tests and the documented two-chiplet CLI pass. New controls include a
scalar analytic solution, an independent augmented exponential integrating both
state and its integral, passive cooling, old-begin prediction equivalence,
geometry negative controls and an unsmoothed 28 K synthetic residual spike.
Refitted predictions have max normalized total-energy residual 1.257e-11 and
max absolute per-interval energy residual 6.891e-12 J. The decomposition MSE
identity error is below 2.6e-15 K². These checks validate mathematics/code.

`ttc-observation-v1` preserves the original completed experiment. `v2` adds
per-interval energy and common/spatial residual diagnostics; refitted parameters
and all original aggregate metrics match v1 exactly. Both frozen input/code
records remain available locally. No production modules changed.

Using the user's authorized `codex-chatgpt-skill`, two completed reviews in
[the existing ChatGPT conversation](https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865)
agreed with the limited interpretation and highlighted fast-dynamics ambiguity,
out-of-range training and the need for spatial residual tests. Adopted changes:
per-interval energy residuals, common/spatial decomposition, explicit reused
holdouts and range-subset wording. This records applied methodology, not a saved
chat transcript or independent verification of the numerical results.

Next: freeze source geometry/materials and make **no new fit** for the first
spatial-model falsification. Compare identical power inputs, end observations,
sensor differences and switch events. If spatial prediction does not improve
across held-out patterns, do not attribute the original residual to spatial
reduction. Audit the common component against explicit ambient/boundary/initial
state evidence as well. Broader ten-metric gates are in `research-gates.md`.
`physical_model_qualified=false`; full Pad/PEX and measured package electrical
channel gaps are unchanged.

## Reproduction

Use the established local environment and original measured-source bootstrap.
Do not run author shell scripts: some remove data. New source acquisition uses
only pinned hashes and locked regular archive members:

```powershell
. ./tools/windows_env.ps1
python tools/audit_ttc_observation.py --bootstrap-upstream --output results/physical-calibration/ttc-observation-fresh
python tools/render_ttc_observation.py --report results/physical-calibration/ttc-observation-fresh/report.json --output <deliverable-directory>
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/physical-calibration/ttc-basic-fresh
```

All output directories must be fresh. Source downloads use official pinned
GitHub paths, retaining TLS verification. Local evidence hashes are recorded in
`docs/evidence/local-ttc-observation.json`.
