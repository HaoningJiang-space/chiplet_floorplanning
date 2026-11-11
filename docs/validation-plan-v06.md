# v0.6 same-interface transistor waveform gate

Continue the fixed GF180 bi_t TX -> SKY130 gpiov2 RX design. Keep `main` only.
A temperature parameter without transistor or characterized timing data is not
accepted as a temperature model. No measured package data exist.

1. Audit the source CDL/SPICE subcircuit closure, primitive models, pin order,
   supply/control domains and correspondence to the existing TT25 libraries.
   Pin public revisions and hashes. Model-name conversion must follow upstream
   conversion scripts, with an auditable element/parameter inventory; no device
   deletion or invented substitutes to obtain convergence.
2. Execute the supported pad circuitry in ngspice at fixed process and voltage.
   First match the GPIO controls and source-library slew/threshold conventions.
   Use explicitly declared output loads; do not add intrinsic capacitance twice.
   Check both transitions, settled logic levels, edge count and finite samples.
3. Sweep fixed-P/V temperatures (0,25,50,75,100,125 C where model applicability
   permits). Separate endpoint interpolation from held-out interior points.
   Input slew/load coverage is a limited experiment, not a full Liberty release.
4. Numerical gates: half-time-step changes <= max(2 ps, 0.5%); rails settle within
   5% of nominal; thresholds cross exactly once per tested edge. Compare measured
   delay/slew at 25 C against the original Liberty: <= max(20 ps,10%) as a
   predeclared agreement gate. An agreement failure remains a finding, not a
   license to fit away missing parasitics. Interior temperature interpolation
   error <= max(5 ps,2%) is a separate model-consistency gate, not silicon proof.
5. A hot-pad link is not enabled unless both pad directions in use, all active
   core timing/constraint arcs and the package model have consistent operating
   points and adequate evidence. Missing closure or baseline disagreement keeps
   the existing TT lane and experimental core profile separate. Complete the
   available device-level experiments and record exact missing dependencies.

Keep raw models/waveforms under `local/` and `results/`; publish original runner
code, compact receipts, explicit rejected assumptions and reproduction commands.
Run unit tests, the original CLI and relevant old/new integration gates before
publishing. Do not start SA merely because a software experiment runs.

Diagnostic additions after the first nominal run: add a 2 pF GF external-load
point to check whether disagreement is confined to high loads, and compare the
four SKY IN tables with the Liberty shipped in the same SPICE build. Both are
controls for alternative explanations; the original tolerances remain fixed.
The 6/12 pF points are diagnostic loads, not assumed electrically legal lanes.
