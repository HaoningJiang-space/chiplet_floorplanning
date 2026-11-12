# Complete routed fabric: Xyce migration control

Starting revision: `f776909e1ef736f74e5b9e27da6bcd3352fda434`; origin was
successfully fetched and main was synchronized. All experiments ran locally.

This is the exact `slot1_rot180` nominal witness circuit: 32 core cells,
eight data lanes, two receivers and a shared forwarded clock. Xyce expands
it to 696 MOS devices, 636 resistors, 653 capacitors and 10 voltage sources.
The actual circuit is checked against the saved Verilog/RC/SPEF before replay.
All primitive files and included cell netlists are checked against the prior
ngspice manifest. The entire physical circuit, supplies, loads and PWL inputs
are preserved; only simulator execution/output syntax changes.

Both experiments run 60 ns at uniform 25 C and 1.8 V with maximum steps of
5 and 2.5 ps. Each tests rising/falling data on every lane. Measurements check
the actual data and capture-clock 50% crossings, settled receiver outputs,
and a unique Q crossing after its capture edge. Setup and hold quantities are
**available windows, not characterized slack**. This is still a core-cell
mechanism experiment with an assumed package, without real Pad qualification.

## Execution and provenance

Both time steps completed and were independently replayed after execution.
All 32 lane/edge/time-step observations passed the capture checks.

| Quantity | Maximum absolute Xyce-minus-ngspice difference across both steps |
|---|---:|
| Available setup window | 1.412822 ps |
| Available hold window | 1.396868 ps |
| Receiver clock-to-Q | 2.028285 ps |

The largest Xyce window change on halving the step was 0.121261 ps. Thus the
whole-circuit discrepancy is larger than this measured numerical sensitivity;
the sub-0.002 ps inverter result cannot be extrapolated to a routed sequential
circuit. This comparison neither isolates the cause nor bounds all numerical
or physical error. It establishes a measured migration baseline for subsequent
nonuniform-temperature comparisons, without fitting offsets into production STA.

[Completed evidence](evidence/local-xyce-fabric.json) and the
[explicit incomplete run](evidence/local-xyce-fabric-timeout.json) are tracked
separately. The final replay reused both completed waveforms, with the original
execution-receipt hashes retained; it is not two additional simulations.

The initial output-pipe run hit 240 seconds without a completed receipt.
Its original runner and deck remain local; no complete log was retained for
that first timeout, so its cause cannot be inferred. The runner was changed
to write directly to a log and retain structured timeout evidence.

The following run completed the 5 ps case in about 238 seconds, then hit the
same limit during the progressing 2.5 ps case. It records `complete=false`
and an explicit timeout for the latter. A subsequent run used a 600-second
limit. Reuse of the completed coarse case requires identical input/STA receipt,
executable and output-column identities; complete artifact hashes; and exact
equality of the regenerated deck. Reused waveforms are independently remeasured.
Timeout cases cannot be reused as completed evidence.

The observed model warnings are retained, not suppressed. BSIM4 version
substitution and source/drain/junction handling remain declared implementation
differences. Passing this comparison would not establish a physical error bound
or validate nonuniform temperature propagation through primitive wrappers.

## Reproduce

```powershell
. ./tools/windows_env.ps1
python tools/compare_xyce_fabric.py results/physical-calibration/integrated-transistors-v1 results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness/reference --output results/xyce-fabric --timeout-s 600
```

An optional `--reuse-run` points to a previous run whose successful cases pass
all the checks above. Raw artifacts remain local; compact published evidence
must distinguish complete and incomplete execution.

The 211-test suite and documented two-chiplet CLI passed. The next substantive
step is to propagate local operating temperatures through the primitive
wrappers and verify uniform-temperature equivalence and independent mixed
temperatures before comparing hot layouts. Goal 01 remains incomplete.

The [actual cell temperature-forwarding controls](core-local-temperature.md)
now pass for the inverter, buffer and flip-flop, including mixed temperatures.
