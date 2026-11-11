# Physical calibration evidence contract

The project owner currently has no sample or measurement dataset. No physical
calibration has been performed. Neither a synthetic sensor file nor agreement
between two solvers can close this gate. All reports keep
`qualification.physical_package_calibration = not_completed_no_measurement_data`
and `complete_package_signoff = false`.

When real evidence becomes available, keep it under ignored `local/` or a
private data store. A calibration campaign needs:

| Record | Required information and units |
| --- | --- |
| Identity | package/sample ID, revision, measurement date, instrument/calibration ID, immutable source file hashes |
| Stack | layer dimensions in mm, materials, measured or sourced conductivity in W/(m K), interface/contact resistances with area convention |
| Power/environment | workload, per-region W and sampling windows in s, ambient/inlet C, heat sink/contact configuration, airflow or cooling boundary |
| Temperature | sensor coordinates in mm and layer ID, readings in C, uncertainty in K, sensor footprint/emissivity for IR, timestamps in s |
| Electrical | transmitter/receiver models and PVT, de-embedded channel reference planes, raw waveforms or S-parameters, termination, jitter, voltage and timing units |

Choose identifiable parameters and tolerances before fitting; do not fit
several unknown conductivities, contact resistances and convection coefficients
from one peak temperature. Split samples or operating conditions into fitting
and independent holdout sets. Preserve raw readings, uncertainty propagation,
residuals, sensor registration, holdout errors and parameter bounds. Check
energy balance and mesh error separately from measurement agreement.

Timing validation additionally needs transistor/IBIS/channel waveform checks,
voltage-level compatibility, slew and loading inside the characterized domain,
the intended clock/phase/jitter budget and the required PVT/variation matrix.
A single calibrated thermal case does not qualify a PHY or an entire package.
