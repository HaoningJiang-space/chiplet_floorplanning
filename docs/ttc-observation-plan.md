# Source-driven TTC observation audit, 2026-11-11

Start: local `2a24b89`, origin fetch succeeded, remote `c124aa9`, clean,
ahead 7 / behind 0. All execution and commits local; no push or remote CI.

## Newly recovered primary evidence

3D-ICE **3.0** commit `1ce8c0ad00b96acae52fc83508c61e3b4ad612df` contains
`test/validation-scripts.tar.gz`. Its `download.sh` points to the exact
Zenodo **3345878** archive used in our previous experiment. It removes both
`sixteen.csv` cases as outside the heatsink fit range. `HS483.mo` documents
power below 40 W. This is an upstream model applicability limit, not permission
to erase our earlier high-power results.

`genpower-batch.sce` uses all recorded `V*I` values without time shifting.
`TTC-*-batch.stk` specifies step 0.01 s, slot 0.1 s and output each slot.
`thermal_data.c` updates power at a slot boundary, solves, and advances time;
`3D-ICE-Emulator.c` outputs completed slots. `compare-batch.sce` compares these
output rows directly with raw temperature rows. Thus upstream **evaluation**
uses interval-end output. This is verified source behavior, not proof of the
hardware logger's timestamp, averaging, latency or antialiasing convention.

The same comparison script alters selected isolated error values using their
neighbors, then reports mean absolute and maximum error. Do not apply this
smoothing to our primary metrics. Our prior RMSE and unsmoothed maxima are not
directly comparable to that source's reported averages/maxima. We do not assert
reproduction of the published simulation or motives for its metric policy.

The author paper (DOI 10.1109/TCAD.2021.3074613, Section VI, Fig. 4) explicitly
reports a 100 C protective cutoff. The recovered code also specifies sensor and
heater geometry, silicon layers, thermal-pad thickness, fan RPM and separate
fitted pad conductivities. These are traced model inputs; fitted conductivity
and heat capacity must not be mislabeled independently measured material data.

## Frozen next experiment, before observing its predictions

1. Preserve all prior source hashes, parameters, cases, starts and error records.
   Lock the recovered upstream files and archive members. Extract a machine-
   readable geometry/provenance record; verify heater power mapping, area,
   sensor coordinates and SI unit conversions. Do not run upstream shell scripts
   that remove data, and do not port their residual smoothing into acceptance.
2. With the **previously fitted** parameters and identical initial states and
   actual native 0.1 s power histories, calculate all three observation models:
   beginning-of-interval (previous convention), end-of-interval (source
   evaluation convention), and exact interval-average temperature (hypothesis).
   All 26 runs, no response-based choice of operator, no fitted fractional lag.
   Quantify the sole effect of the observation operator. Keep raw MAE, RMSE and
   maximum residual on the native time grid and original 1 s reporting grid.
3. Then refit **only the interval-end convention**, chosen from the upstream
   evaluation code, using the same four calibration patterns per group and all
   four starts/bounds as before. Report the nine predetermined held-out cases,
   already examined in previous rounds: this is not blind validation.
   Keep the same 1 s residual sampling, equal run weights, 200 evaluations and
   tolerances. Initial cell state and conditional bath inference are unchanged;
   they represent the pre-interval state by assumption, not extra measurements.
   Report a secondary diagnostic excluding the first conditioned second.
4. No smoothing or dropped cases in primary metrics. Report the 24-run
   upstream power-range subset additionally, with both `sixteen` cases still
   separately visible. Range-subset reporting is not a new train/test split.
5. For modes z'=u-lambda*z, use analytic exponential propagation and analytic
   interval integrals. Audit all N input intervals, including the last input,
   against storage changes and integrated boundary loss. Check a scalar analytic
   example, an independent augmented matrix exponential and a synthetic spike
   that must remain in reported error. Geometry conservation controls must catch
   a missing half-heater and mismatched sensor-to-input association.

## Interpretation restrictions

Improved interval-end residuals establish sensitivity to a verified evaluation
choice. They cannot establish true logger timing or uniquely attribute the old
28 K discrepancy. Sensor lag/averaging, spatial reduction, ambient drift,
fixture/contact variability and source uncertainties remain distinct possible
causes. No fitted parameter is transferred to production or called a uniquely
identified material quantity. Full GPIO/PEX and measured package electrical
channel gaps remain unchanged. `physical_model_qualified=false` throughout.
