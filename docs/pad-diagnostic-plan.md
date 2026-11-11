# Pad nominal mismatch diagnostics — pre-run contract, 2026-11-11

Local main `2dbd03b`; successful fetch, origin/main still `c124aa9`.
Local experiments only, no push or remote CI. No optimization or hot-pad release.

Competing explanations are measurement definitions, load-axis interpretation,
and incomplete/different transistor netlist, parasitics or device models.
No model changes, offset fitting, threshold fitting or selection of the most
favorable load mapping is allowed. Existing v0.6 nominal mismatch is retained.

1. Reproduce the 14 v0.6 transients on this Windows host with unchanged model
   hashes. Record the actual simulator version; the previously used ngspice 42
   executable download returned HTML rather than the verified archive. Use the
   official MSYS2 archived ngspice 42-1 package with pinned runtime hashes, and
   explicitly compare with the old ngspice 42 results rather than assuming build
   identity. An initial MSYS2 ngspice 47 trial rejected the GF behavioral-capacitor
   expansion (`unknown parameter (e9)`); retain it as an execution failure,
   not evidence for physical mismatch. No PDK changes were made to suppress it.
2. Extract the original library headers: time/capacitance units, input/output
   thresholds, slew thresholds, derate, and supply definitions. The GF header
   is the original IO library header used by assembly, not the cell-only file.
   Check these against the unchanged waveform generator and measurement code.
   Re-measure saved waveforms with source-defined crossing thresholds.
3. Fixed GF TT25/3.3 V matrix: input slew 0.08/0.18/0.5 ns × external output
   capacitance 1/2/3/4 pF (12 points). They are candidate low-load diagnostics;
   check actual output slew and table domains before labelling any point legal.
   Primary mapping A is `C_axis = C_external + 2.977816 pF`; competing B is
   `C_axis = C_external`. Do not extrapolate B below the table's minimum load.
   SPICE contains only the external capacitor under both interpretations.
4. Freeze four anchor points from the existing 3 mm GPIO `bridge-reviewed`
   record: `tx_data_pad` and `rx_data_pad`, max-mode rise and fall. Save the
   source report hash, selected arc, slew and Ceff. For GF use A to translate
   Ceff to external C. Simulate both transitions but compare the selected edge
   as the anchor. A lumped Ceff load reproduces a table operating point, not the
   distributed package channel or the STA-determined Ceff calculation.
5. Include the existing SKY nominal point (1 ns, 0.022799 pF) as a diagnostic.
   Keep its empty subcircuits and simulator warnings visible; no temperature
   sweep for SKY or characterization release based on apparent agreement.
6. Run all 17 new configurations at 5 and 2.5 ps maximum steps (34 transients).
   Preserve the v0.6 rail/single-crossing checks, numerical convergence gate
   `max(2 ps, 0.5%)`, and nominal agreement gate `max(20 ps, 10%)`.
   Nominal failure is a reported model finding, not an execution failure.
7. Report every adjacent load difference at fixed slew, and every adjacent slew
   difference at fixed load: 17 pairs × four metrics. Use the fine-step results.
   Report signed SPICE and table differences, their residual, and the sum of
   both endpoints' observed step changes as an empirical numerical screen.
   Table queries are deterministic interpolation of source data; this does not
   bound interpolation/model error. For near-zero differences do not divide by
   the change or manufacture a relative accuracy percentage. No physical
   sensitivity qualification threshold is set without a sourced decision budget.

Independent ChatGPT supervision requested checks of competing hypotheses,
source-defined measurements, actual STA anchors and separate differential
error accounting. These are incorporated before running the new matrix.
An empirical step-change screen is not a rigorous error bound. Absolute failure
plus matching finite differences cannot authorize a temperature timing model.
