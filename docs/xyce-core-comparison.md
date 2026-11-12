# Actual SKY130 inverter: cross-simulator temperature comparison

Origin was fetched at `cd97da28f0f5adc7e3a984b7dd809dcd388b4f65`, with a clean,
synchronized main. All experiments ran locally on Windows CPU.

The pinned `inv_1` schematic and all 837 primitive-source files were checked
against the existing ngspice experiment. Twelve saved cases were replayed in
XyceNF 7.10.0: temperatures 25/62.5/100 C, output loads 0.00952062/0.0254232 pF,
and maximum steps 2/1 ps. Each 10 ns run uses the same 1.8 V supply, input PWL,
0.122474 ns 20–80% input slew and physical circuit. Only simulator control and
output syntax is translated. Original waveform/deck hashes are checked and
ngspice metrics are independently remeasured before comparison.

The measurement verifies finite increasing time through 10 ns, actual input
slew, threshold crossings and settled output rails. Both models use 50% delay
and 20–80% slew. Xyce's nonlinear tolerance semantics are not assumed identical
to ngspice's; the 2-to-1 ps comparison measures sensitivity to the declared
maximum step, not all solver errors.

| Metric | Xyce minus ngspice across all cases (ps) | Difference in 25→100 C increment (ps) | Largest Xyce step change (ps) |
|---|---:|---:|---:|
| Falling delay | -0.000726 to +0.001557 | -0.000092 to +0.000892 | 0.005053 |
| Rising delay | -0.000640 to +0.000806 | -0.000938 to +0.000014 | 0.002562 |
| Falling slew | -0.006886 to +0.006310 | -0.001519 to +0.003984 | 0.028476 |
| Rising slew | -0.007504 to +0.006703 | +0.000004 to +0.001569 | 0.012733 |

Despite model implementation differences, the tested inverter's maximum delay
discrepancy and temperature-increment discrepancy are smaller than the maximum
tested step sensitivity. This does **not** establish a physical error bound,
agreement with Liberty characterization, receiver constraints, or a layout
ranking under a nonuniform thermal field.

## Explicit differences and retained failures

Each execution retains nine warnings: one duplicate equal-valued SCALE parser
option, two BSIM4 4.5→4.6.1 substitutions, two pbswgd minimum clamps, and four
source/drain conductance resets. These warnings are not suppressed or declared
physically harmless. Evidence marks physical qualification false and records
warning counts and full log hashes. PDK sources were not modified to remove
warnings or tune agreement.

The initial translation failed because of solver-option dialect and leading
whitespace handling. Its deck and error log remain in local
`results/physical-calibration/xyce-core-native-v1`. The corrected exploratory
run is retained separately as `xyce-core-native-v2`. Neither is substituted
for the final twelve-case experiment.

The actual wrapper scopes its model inside the primitive subcircuit; this
experiment only uses uniform global temperatures. It does not establish that
the mixed-temperature model-sharing issue found in the manufactured probe is
absent in full circuits. That needs its own local-temperature control.

## Reproduce and next step

```powershell
. ./tools/windows_env.ps1
python tools/compare_xyce_core.py results/physical-calibration/core-inverter-v2 --output results/xyce-inverter
```

[Compact evidence](evidence/local-xyce-inverter.json) contains per-case paired
metrics and artifact hashes; raw decks, waveforms and logs remain local.
The full 211-test suite and documented two-chiplet CLI passed again.

Next extend the same comparison to the buffer and flip-flop, then the exact
32-cell routed fabric. Validate temperature propagation through primitive
wrappers with identical-temperature and mixed-temperature controls before
interpreting nonuniform-temperature timing. Receiver constraint characterization
and real Pad/package qualification remain open; Goal 01 is not complete.
