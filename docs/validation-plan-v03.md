# v0.3: pad, PVT and local temperature evidence gates

Declared before v0.3 experiments. The user has no physical package samples or
measurement data. Physical calibration and package signoff therefore remain
unavailable; simulation agreement cannot satisfy this gate.

1. Load pinned public SKY130 and GF180 cell and pad libraries. Retain original
   tables, thresholds, supply domains and source hashes. Reject absent models,
   missing paths, electrical violations and incomplete parasitic annotation.
   Run an explicit 3.3 V GPIO lane with both package data and forwarded clock.
   This tests pad timing integration, not a high-speed protocol PHY or SI/BER.
2. Enumerate supported PVT points, including independent die corners. Never
   substitute a different voltage for a missing temperature characterization.
   Report the requested/available coverage and unsupported pad combinations.
3. Map individual instances to local temperatures with die rotation included.
   Temperature interpolation requires equal process/voltage, identical table
   topology and axes, bracketed temperatures, and separate instance cell names.
   Identity at endpoints, uniform-temperature equivalence, data-only versus
   clock-only perturbations and out-of-range rejection are software gates.
   Interpolation accuracy between measured/characterized points remains
   unvalidated without independent holdout characterization. Do not assume
   that every delay increases with temperature.
4. Separate physical calibration evidence from software tests. Missing real
   data must remain machine-readable in the main evaluation report.

Preserve failures and explain their causes rather than changing acceptance
limits to make results pass. Run the full unit suite, original two-chiplet CLI,
existing package/electrical regressions and new integration cases before
publishing. Keep raw libraries and results ignored; publish commands, hashes,
compact receipts and explicit remaining gaps.

## Evidence-driven refinements during implementation

The source SKY130 DFF tables use different load axes at the two temperatures.
Rejecting these tables would prevent interpolation. The adapter therefore first
resamples both tables on the union of knots **inside their common domain**,
then interpolates in temperature. Outside-domain points remain forbidden.
An analytic bilinear test checks this additional numerical operation.

The first integration run (`v03-validation-01`) failed an overly general check
that heating a data buffer and a clock buffer must change setup in opposite
directions. The initial plan explicitly did not assume monotonic temperature
delay. Expanded paths show the data rising delay falls while the clock falling
delay rises in this FF library. Preserve this rejected expectation. Replace
that assertion with independent interpolation of the original endpoint tables
at the actual input slew/effective capacitance (error <= 2e-6 ns) and explicit
required-minus-arrival arithmetic (error <= 1e-5 ns). These tolerances cover
OpenSTA's float/report precision, not physical model error.
