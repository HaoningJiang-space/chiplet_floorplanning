# Complete-fabric uniform-temperature controls

Both local experiments completed on 2026-11-12. Their original receipts remain
unchanged; `tools/summarize_xyce_uniform.py` independently rereads the waveforms,
hashes, strict diagnostics, circuit export and transformed models. Compact
replay evidence: [local-xyce-uniform-controls.json](evidence/local-xyce-uniform-controls.json).

| Temperature | Maximum absolute local-minus-global difference | Numerical screen |
|---|---:|---|
| 25 C | 0.0101775949162 ps | Passed |
| 65 C | 0.0173860523489 ps | Passed |

Each maximum covers 16 lane/edge events and three quantities: setup available
window, hold available window and receiver clock-to-Q. All four 60 ns runs use
a 2.5 ps maximum step. Each log contains 2,785 known warnings and zero unknown
or suppression messages. Recognized warnings are retained, not proven harmless.

The global variant uses original models at the stated global temperature. The
local variant keeps global ambient at 25 C and forwards that same stated
temperature to all 32 cells through instrumented wrappers. RC, supplies and
stimuli are fixed; the local circuit export order follows the hot exporter.
Therefore the measured discrepancy includes export-order sensitivity. This
test does not isolate a physical device effect or calibrate a real PHY/Pad.

The 0.5 ps screen was specified before either result. Passing it is a numerical
control result, not a physical error bound. The replay explicitly distinguishes
`execution_complete=true`, `numerical_control_passed=true`, and
`physical_qualified=false`. Future raw reports carry the same separate states;
the earlier raw receipts retain their original schema and hashes. Regression
tests show that a completed 2 ps discrepancy is unresolved, not admitted.

The cold/hot three-layout experiments remain pending. Their runners now use the
same strict diagnostic/observation admission and retain structured failed cases.
Historical warning-suppressed runs cannot be reused as admitted cold evidence.
No new layout-ordering or optimality conclusion follows from the controls above.

Validation for this milestone: 236 local unit tests and the documented
two-chiplet CLI (3 W, 34.1886 C; uncalibrated, timing not run).
