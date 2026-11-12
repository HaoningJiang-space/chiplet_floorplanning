# Sequential-cell diagnostic for the integrated decision model

The finite layout optimum remains conditional on its declared core-cell model.
Before interpreting an electrothermal change in feasibility, the sequential
contribution must be checked as well as the buffer, inverter and passive RC.
For a data path, launch clock-to-Q contributes to arrival time; capture setup
and hold constrain a different event. A combinational delay discrepancy cannot
be transferred to those sequential quantities as a universal correction.

This stage examines only `sky130_fd_sc_hd__dfxtp_1` clock-to-Q, with data well
separated from the capture edge. It does not characterize setup/hold, estimate
metastability resolution, or validate a complete chiplet interface.

## Frozen experiment

- Cell netlist: Google SKY130 HD revision
  `ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1`, exact SHA-256
  `39049c3c6a74ac24fdc0d93528dd5b0e15f7ef51729008913bdeeee0d8ead2df`.
- Same local primitive-model preparation and ngspice executable as the earlier
  core diagnostics; consumed inputs and executable hashes are retained.
- TT, 1.8 V, 25/62.5/100 C; fixed clock and data 20–80% slew 0.122474 ns.
- Fixed external capacitors 0.00900162 and 0.0235923 pF; these are 25 C table
  knots, not independently measured receiver loads. Other queries stay bounded
  within the temperature-interpolated Liberty tables.
- Rising clocks begin at 1/7/13 ns. The first captures zero, then the next two
  capture one and zero. Data transitions precede the latter two clocks by
  2 or 3 ns at their 50% crossings. No initial condition forces the output.
- Maximum time steps 2 and 1 ps; 18 ns transient. The 3 temperatures × 2 loads
  × 2 data advances × 2 steps yield 24 waveforms, each measuring both Q edges.
- Delay is clock 50% to Q 50%; output slew is 20–80%. Stable output windows
  must be within 1% of the expected rail. This is a diagnostic capture check,
  not a setup/hold failure criterion or a model accuracy threshold.

The replay tool verifies artifact hashes, domain completeness, saved deck
conditions, actual data transitions, output capture and unique threshold
crossings. It recomputes both waveform measurements and bounded Liberty
queries. Independent constructed waveforms verify the measurement arithmetic;
missing captures, multiple crossings and incomplete time records are rejected.

```powershell
. ./tools/windows_env.ps1
python tools/audit_core_ff_spice.py --output results/core-ff-cq
python tools/summarize_core_ff_spice.py results/core-ff-cq --output results/core-ff-summary.json
```

## Completed local result

All 24 waveforms completed and passed replay. Across delay and slew quantities,
halving the time step changed results by at most 0.024646 ps; changing data
advance from 2 to 3 ns changed results by at most 0.014522 ps. Across the two
loads and both edges, the SPICE-minus-Liberty discrepancy in the 25-to-100 C
clock-to-Q change ranged from -5.066975 to -1.450706 ps. The absolute discrepancy
across delay and slew measurements ranged from -143.885420 to -4.153187 ps.
The tested time-step effect is much smaller than the cross-model differences;
this does not identify their cause or establish a physical error bound.
See [saved evidence](evidence/local-core-ff-cq.json).

## Interpretation limits and next decision

The public schematic netlist and public Liberty views do not establish identity
with the original extracted characterization circuit, primitive revision or
stimulus deck. Supply and stimulus currents are saved, but a complete active
compact-model charge/energy audit is not performed here. No fitted delay offset
or temperature correction is admitted to production STA.

For setup/hold, the saved Liberty data explicitly records
`violation_delay_degrade_pct: 10`. That is useful source evidence, but it does
not identify every characterization condition (including the constraint load
and search protocol). A later boundary experiment must preserve the distinction
between clock-to-Q degradation, correct logical capture and non-resolution;
it must not silently treat any one of these as an equivalent silicon constraint.

This remains a component diagnostic on the path to a common data/clock
reference calculation. It does not close Pad/ESD, package channel, jitter,
process variation or thermal boundary calibration, and it does not change the
existing finite-domain zero-temperature-cost proofs or qualify them physically.
