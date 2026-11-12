# Shared-clock multi-lane numerical contract

Start at `a629b0c`; origin fetch succeeds at `c124aa9`. All work runs locally.
This stage advances timing bookkeeping for the ten-metric goal, alongside the
ongoing finer thermal calculations. It does not substitute synthetic constant
delay cells for real Pad/PHY or extracted package characterization.

Use 2, 4, 8 and 16 chiplets: one transmitter and 1, 3, 7 or 15 receivers, each
with eight independent data lanes. One physical common root drives buffered
transmitter clock banks and a single forwarded-clock trunk; one branch and
inverter per receiver drive its eight capture flops. Root/trunk are instantiated
once, so shared loads are summed once rather than duplicated per lane. Explicit
clock-bank buffers keep synthetic fanout within the declared 1 pF limit. This
is a connectivity/capacitance constraint, not a package routing certificate.

Source period is 10 ns with falling edge at 4 ns. Launch flops are rising-edge;
capture after an inverter uses the source falling edge. Enumerate logical edges
before adding propagation delays, even when a clock delay exceeds a period.
Report every lane's setup/hold and rise/fall path, not just the global worst path.
For each compare launch/capture events, actual endpoint arrivals, required time,
slack, cell increments, pin slew, physical fanout capacitance, and any common-path
correction against an independent event-time model. Fixed tolerance is 1e-5 ns
for reported times and 1e-6 pF for printed capacitance.

Use scalar synthetic Liberty cells with separate rise/fall delays and an
explicit 0.01 pF sink input capacitance. The edge reference reads no Liberty or
STA report. Early/late delays are synthetic bounds, not PVT signoff. Root
uncertainty alone has a declared physical correlation: one additive delta in
[0, 0.2] ns changes both polarities together. Enumerate its two endpoints to
obtain the correlated worst slack, separately from pessimistic independent
launch/capture bounds. Compare OpenSTA with and without same-pin common-path
pessimism removal. This assumption does not cover arbitrary unequal variation,
cycle jitter, sensor uncertainty, actual PVT or probability distributions.

Controls frozen before running:
- One-lane reference; 2/4/8/16-chiplet networks; correlated 16-chiplet network.
- Delay only one data lane, only one receiver's branch, or the shared trunk.
- Add the same delay to both common-root polarities: absolute arrivals move,
  setup/hold slack stays unchanged. Delay only the common root's falling edge:
  capture phase and setup/hold margins change with opposite signs.
- Preserve a localized setup failure and a network-wide hold failure.
- Reject missing capture clocks, wrong capture polarity, a missing lane report,
  a wrong lane endpoint and overloaded clock-bank outputs.

Root delay cancellation is not a universal wirelength rule: launch/capture
transition, clock branch identity and logical edge pairing all matter. A shared
clock's delay perturbation affects multiple lanes coherently. Clock graph and
resource identity must eventually connect to a single legal routed network;
this fixture alone does not establish bump escape, routing capacity, signal
integrity, whole-link power, thermal feedback or optimized-placement quality.

Review the complete substantive stage and relevant Git history after its
experiment suite is complete, following the user's goal-level review cadence.
