# First complete per-instance hot-fabric diagnostic

This local Windows experiment uses the nominal `slot1_rot180` witness and its
saved `floorplanning.evaluate()` temperature field, local device assignments
and heated RC/SPEF. The package and fixed 3 W power map remain assumptions;
the thermal peak of 66.353202 C is not a measured junction temperature.

The 32 core cells receive their individual mapped operating temperatures
(approximately 64–66 C) through the verified cell/primitive/MOS parameter
chain. Each conductor uses the same layout's heated resistance. Circuit
topology, capacitance, cell identities, 1.8 V supply, 20 ns clock, stimuli and
loads are unchanged. This is one-way fixed-power temperature feedback, not a
self-consistent leakage/activity/temperature solution.

Two new 60 ns Xyce simulations use maximum steps 5 and 2.5 ps. The preserved
uniform-25-C Xyce runs provide the baseline. The actual hot deck is reconstructed
from the verified feedback Verilog/RC/SPEF, not inferred from center distances.
The independent summarizer checks raw artifact hashes, exact CSV headers,
actual circuit/temperature assignments, transformed model hashes, complete
waveforms and receiver capture events before calculating changes.

## Result for this layout

| Available window | Minimum at 25 C | Minimum with feedback | Per-path feedback changes |
|---|---:|---:|---:|
| Setup | 9.870691992 ns | 9.880171645 ns | -12.262304 to +9.479653 ps |
| Hold | 9.938324537 ns | 9.949121318 ns | -9.490631 to +12.304876 ps |

The minimum windows improve by about 9.480 ps and 10.797 ps respectively,
but individual paths can worsen. Minima are recomputed over all lanes and
edges, without assuming a fixed critical path. The 16 lane/edge cases and
two window types have **zero opposite change directions** between Xyce and
STA at the fine step. The largest difference between their predicted thermal
effects is 1.319150 ps. Halving the time step changes the paired Xyce thermal
effect by at most 0.253023 ps. These are observed sensitivities, not bounds on
unmodeled physics or all numerical error.

[Replay evidence](evidence/local-xyce-hot-rot180.json) contains all 64
time-step/lane/edge/window records. Raw decks, waveforms, model copies and
logs stay local. The initial runner source is preserved with its recorded
hash; later independent replay adds the review-requested header checks.

This experiment does not yet establish temperature-induced layout interaction:
the other two candidates have not been simulated with feedback. It also does
not close the requested full-fabric uniform local/global hot-temperature
control. That control remains necessary to strengthen attribution beyond the
18 single-cell propagation checks. The exporter preserves physical elements
but places the reconstructed circuit together near the end of the deck; a
matched uniform full-fabric control will also check numerical sensitivity to
that export organization. No production calibration correction is fitted.

The reported quantities remain available windows, not setup/hold slack.
Independent receiver-constraint characterization, actual Pad/ESD and package
qualification remain open. No physical optimum or joint-optimization advantage
is claimed. The earlier finite-model zero timing-temperature-cost result is
not replaced by this single-layout diagnostic.

## Reproduce

```powershell
. ./tools/windows_env.ps1
python tools/audit_xyce_hot_fabric.py results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness results/physical-calibration/xyce-fabric-rot180-reviewed results/physical-calibration/integrated-transistors-v1 --output results/xyce-hot
python tools/summarize_xyce_hot.py results/xyce-hot results/physical-calibration/xyce-fabric-rot180-reviewed results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness --output results/xyce-hot-summary.json
```

The full 221-test suite, documented two-chiplet CLI and actual-cell helper
regression passed locally during this stage. Goal 01 remains active.

Later [diagnostic replay](xyce-strict-diagnostics.md) found warning suppression
in these historical logs. The window comparisons above remain preserved
numerical observations, but complete warning coverage is unproven. They must
not be promoted to full model admission on the strength of known displayed
warnings alone.
