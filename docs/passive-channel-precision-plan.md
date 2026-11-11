# Stronger transient error-control follow-up

Declared before this follow-up, while the fixed-step refinement is finishing.
Keep all previous results unchanged. A smaller maximum step did not uniformly
clear the fast RLC endpoint-waveform gate: the 1 mm/25 ohm/N32 error is about
0.552 mV at 0.25 ps and 0.528 mV at 0.0625 ps, versus the fixed 0.33 mV gate.
At 0.25/0.125 ps maximum step, actual median steps near the largest error are
already about 0.068 ps. The maximum step is not the sole accuracy control.

Run all six 100 ps RLC conditions at N8/N16/N32 with max step 0.125 ps and
N32 again at 0.0625 ps: **24 new runs**. Use Gear, maximum order 2, but specify
reltol=1e-9, abstol=1e-16 A, vntol=1e-11 V, chgtol=1e-20 C and trtol=1.
These are stronger numerical controls, not physical parameter fitting. Retain
the original conservation, 0.33 mV waveform, 0.1 ps crossing and refinement
gates without change. All source events, R/L/C, reference planes, thresholds
and independent oracle values remain fixed. Print actual solver options into
the run logs. Compare over/undershoot and all crossings as before.

The [ngspice manual's simulator options](https://ngspice.sourceforge.io/docs/ngspice-43-manual.pdf)
document separate relative, absolute charge and transient truncation controls.
This reference documents their meaning; the actual installed executable remains
hash-locked ngspice 42. A combined numerical-control change cannot establish
which individual setting caused an earlier mismatch or the trapezoidal timeout.
Do not claim that attribution without a separate ablation.

Reuse the 72 passed records outside the fast-RLC group from `matrix-refined/`
only after exact deck, solver/runtime, source/oracle, gate, measurement and
lossless waveform checks. This supplies 96 analysis records (24 new + 72 reused)
in `matrix-precision/`. Spatial/temporal comparisons within every case retain
one consistent integration method and tolerance set. All earlier failed runs
remain failed; no claim of real PHY or continuous-band qualification is made.

## Cost control and lossless binary storage follow-up

The strict attempt completed N8/N16 at 1 mm/25 ohm (both passed), but N32 hit
the 180 s process limit; the following N32 half-step run was deliberately
stopped to diagnose cost. Preserve the two completed runs, timeout record/log,
partial files and explicit interruption status. This was not a completed sweep.
The N16 text waveform exceeded 2 GB; one N32 process used about 9 GB of memory.
Do not infer a physical failure from this process-time limit.

A separately declared one-case control in `precision-cost-control/` uses
reltol=1e-8, abstol=1e-14 A, vntol=1e-9 V, chgtol=1e-18 C, trtol=1 at
1 mm/25 ohm/100 ps/N32/max step 0.125 ps. It completed 488034 samples in
55.422 s including text export, passed the original gates, and had 0.032651 mV
maximum endpoint difference. These controls are not physical model parameters.

Before a new full fast-RLC sweep, freeze this cost-controlled profile uniformly
for all six fast RLC cases, N8/N16/N32 at 0.125 ps, N32 also at 0.0625 ps:
24 new runs in `matrix-balanced/`, with the same 72 passed records reused from
`matrix-refined/`. Do not reuse the unfinished strict sweep as a passed matrix.
All original external acceptance gates and physical values remain unchanged.

Use ngspice native real binary export of exactly the same selected adaptive-time
vectors; no interpolation, decimation or dropped samples. A separate RC control
in `binary-control/` writes text and binary from the **same transient run**;
require identical shapes, times/vectors within text-rounding tolerance 1e-13,
validated column names and exact payload size. Archive native binary losslessly
with gzip and verify its decompressed hash before removing the fresh raw file.
This changes evidence storage, not the circuit or integration. Keep both export
formats and the comparison receipt for that control. The fixed reader supports
the installed x86_64 little-endian real transient format and rejects complex,
truncated, extra-payload or misordered-column files.
