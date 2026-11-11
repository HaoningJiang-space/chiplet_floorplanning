# Source-synchronous timing semantic experiment

Contract frozen before examining STA results, based on main `38db063`.
This experiment independently checks edge semantics under synthetic constant
cell delays. It does not qualify any PDK, pad waveform, package channel or PHY.

- One launch clock, period 10 ns, waveform {0, 4} ns. Positive-edge launch and
  receive flip-flops; the forwarded clock traverses a buffer and an inverter.
- `create_generated_clock -divide_by 1 -invert` at the inverter output; clocks
  propagated. No jitter, uncertainty, OCV, wire delay, crosstalk or temperature.
- Rise/fall constants in ns: CQ 0.7/0.9; data buffer 1.3/1.2;
  forward clock buffer 0.9/1.1; inverter 0.4/0.8;
  receiver setup 0.2/0.35; hold 0.15/0.1.
- The reference enumerates ideal source events, identifies the next and previous
  falling edges relative to launch, then adds clock propagation. It never pairs
  edges again after adding physical delay. A deliberate long clock delay must
  remain a hold violation.
- Check all four setup/hold × rise/fall paths, not only worst slack. Compare
  launch/capture edges, data/capture arrival, required time and slack against
  `full_clock_expanded`. The pinned engine displays setup launch at 0 and hold
  launch at P, with capture at fall in both. Subtract the fixed 0/P from every
  absolute time in the corresponding path; never fit an offset from its result.
- Fixed absolute comparison tolerance: 1e-5 ns (0.01 ps), chosen for six-decimal
  printed times and OpenSTA float arithmetic, not as a physical error budget.
- Data-only +0.5 ns: setup decreases, hold increases by 0.5 ns. Clock-only and
  inverter-only +0.5 ns: inverse changes. Common +0.5 ns: slack unchanged while
  both arrivals change. Period 12 with falling edge fixed and falling edge 6
  with period fixed separately distinguish period from duty-cycle behavior.
- Data +4 ns forces setup failure; clock +7 ns forces hold failure. Failures
  remain valid computed results. Semantic mutations (missing inversion,
  missing generated-clock declaration, ideal capture clock) must fail the
  declared contract; absence of a generated clock need not eliminate timing
  paths because the primary clock may still propagate through the inverter.
- Original upstream SDF/min-max Liberty/SPEF reports are checked separately.
  This first constant-corner experiment does not establish early/late corner,
  uncertainty, min-pulse-width, metastability, CDC or transistor-waveform coverage.

Nominal hand reference, normalized to launch at zero: setup capture ideal edge
4 ns, propagated capture 5.5 ns; hold capture ideal edge -6 ns, propagated -4.5
ns. Rise/fall data arrival is 2.0/2.1 ns. Setup slack is 3.3/3.05 ns; hold slack
is 6.35/6.5 ns. The buffer falling delay and inverter rising delay occur exactly
once on the capture path. Independent review may add stricter checks, but cannot
silently relax tolerances to turn a failing run into a pass.

Pre-result independent-review revision: inverter fall changed from 0.6 to 0.8
ns, so the wrong rise-buffer/fall-inverter combination (1.7 ns) cannot equal
the correct 1.5 ns capture latency. Raw arc transitions must also be checked.
Add wrong FF polarity, swapped clock-buffer arcs, wrong data endpoint and
missing output constraint as structural negative controls.

A second, separate early/late case uses the constants above as late and
CQ 0.3/0.5, data 0.8/0.7, clock 0.4/0.6, inverter 0.2/0.5 ns as early.
Constraints stay identical; explicitly select `on_chip_variation` analysis.
Setup compares late data with early capture; hold compares early data with late
capture. A swapped min/max library assignment must be rejected. This remains
synthetic min/max semantics, not a measured PVT/OCV distribution.
