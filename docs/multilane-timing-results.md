# Shared-clock multi-lane timing: numerical stage

Local implementation commit `fcf0dcb`, successful origin fetch at `c124aa9`.
The complete v2 suite runs 15 declared event scenarios and five erroneous-model
controls on pinned OpenSTA 2.2.0 (`02b129d48fbefb57d08f4bc412700ddfa24a159b`).
All numerical contract checks pass: 1,668 setup/hold/rise/fall path results and
40,544 numeric time fields, with maximum reported difference about 1e-6 ns,
below the frozen 1e-5 ns tolerance. Physical fanout capacitance checks also pass.
There are 157 passing software tests plus the original two-chiplet CLI case.

This is a completed numerical timing substage, not completion of goal 7. The
fixture has artificial scalar Liberty delays and capacitances. Real Pad/PHY,
package routing capacity, extracted channels and thermal feedback remain open.

## Scale and shared identity

| Chiplets | Receivers | Data lanes | Checked paths per scenario | OpenSTA process time / s |
|---|---:|---:|---:|---:|
| 2 | 1 | 8 | 32 | 0.054 |
| 4 | 3 | 24 | 96 | 0.080 |
| 8 | 7 | 56 | 224 | 0.105 |
| 16 | 15 | 120 | 480 | 0.200 |

Times are one local invocation on this synthetic fixture, including process
startup but excluding Python preparation/reporting. They are not a scaling
claim for full real-library designs or a routed physical implementation.

One common clock root and one forwarded-clock trunk are physically instantiated
once. A transmitter clock bank and a receiver branch/inverter exist per receiver.
Each receiver's eight data flops share that receiver clock. Reported root load
is `(receivers+1)*0.01 pF`, trunk load is `receivers*0.01 pF`, and each bank/capture
driver load is `lanes*0.01 pF`. The largest root load is 0.16 pF. These are
connectivity-derived synthetic loads, not measured bump or package capacitance.

Every endpoint is checked; reporting only the worst global path would miss
localized changes or a missing lane. The parser verifies path count, unique
endpoints, clock identity, polarity, early/late selection and pin increments.

## Physical distinctions tested

- A 0.5 ns perturbation to one data lane changes only that lane's margins.
- A 0.5 ns receiver-clock branch perturbation affects all eight lanes of that
  receiver; other receivers retain their original event times.
- A 0.5 ns forwarded-trunk perturbation moves every capture time, increasing
  setup slack and decreasing hold slack by 0.5 ns.
- Adding 0.5 ns to both common-root polarities moves absolute launch/capture
  times equally and leaves slack unchanged.
- Adding 0.5 ns only to the common-root falling edge changes effective duty
  cycle. Setup gains 0.5 ns and hold loses 0.5 ns. Common hardware identity alone
  does not imply equal delay changes for the two polarities.

The fixed logical edge pair is preserved even when clock delay exceeds a period.
The setup-failure case has minimum -3.65 ns; the hold-failure case has minimum
-1.25 ns. These are correctly detected failing timing margins, while event
calculation still agrees with the independent reference.

## Explicit, limited correlation check

Only the common root has a declared coupled uncertain quantity: the same
additive delta in [0, 0.2] ns shifts both rise and fall delay. The independent
oracle enumerates the two endpoints as one variable. Other early/late delays
are assigned by the frozen setup/hold contract; constraints stay fixed.

OpenSTA without common-path correction includes 0.2 ns pessimism. With
`sta_crpr_enabled=1` and `sta_crpr_mode=same_pin`, every path recovers 0.2 ns and
matches the enumerated correlated-root slack. For the first lane, setup rise/fall
are 3.36/2.81 ns and hold rise/fall are 5.18/5.51 ns. The source's implementation
for different transitions was inspected at the pinned `search/Crpr.cc`; the
independent numerical expectation came from the declared shared variable, not
from copying the implementation formula.

This does not authorize generic rise/fall correlation, arbitrary PVT bounds,
cycle-to-cycle jitter or probabilistic yield. Such models require characterization
of the actual same interface and physical shared paths.

## Negative controls and remaining integration

The suite rejects missing generated clocks, incorrect capture polarity, a missing
last-lane report, a wrong lane endpoint and a deliberately overloaded clock bank.
All inputs, executable, source files and full STA logs are hashed. The original
v1 and its preparatory pilot remain local; v2 also hashes all imported fixture
helpers and records the executable version.

Next, attach one shared clock-net identity to legal package routing resources,
including branch loads and unique conductor occupancy. Validate finite capacity
and distinguish a search failure from proven infeasibility. Real Pad/channel
characterization remains a separate prerequisite for physical timing claims.
Do not use this synthetic evaluator to claim real optimum frequency, thermal
timing coupling, joint-layout benefit or SOTA quality.

No micro ChatGPT review was requested. The user asked to review the complete
substantive goal/stage and its relevant Git history after integrated completion.

Reproduce locally:

```
python tools/validate_multilane_timing.py --output results/physical-calibration/multilane-timing-new
python tools/render_multilane_timing.py --input results/physical-calibration/multilane-timing-new --output PATH_TO_OUTPUTS
```

Compact evidence: `evidence/local-multilane-timing.json`. Full local records:
`results/physical-calibration/multilane-timing-v2`.
