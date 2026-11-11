# v0.3: characterized corners, GPIO rejection and local-temperature coupling

Validated 2026-11-11. This milestone extends the software evaluator; it does
**not** complete package signoff. The owner has no physical sample measurements.
Raw evidence is in ignored `results/v03-final-characterization`, `v03-package-regression`
and `v03-electrical-regression`. A compact receipt is in `evidence/v03-validation.json`.

## Source and model scope

All downloads are pinned by commit and SHA-256 in `tools/sources.lock.json`.

| Source | Commit | Use |
| --- | --- | --- |
| Google SKY130 HD | `ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1` | common/corner JSON and original buf_8/dfxtp_1 tables |
| open_pdks | `5740c4a81c42f9fe4af5ef2ee258a99151053d28` | SKY130 gpiov2 pad TT/25 C, core 1.8 V, I/O 3.3 V |
| Google GF180 I/O | `2aeec51ea2824b6cc0b396acfc39f4535f40b23a` | library header plus in_c TT/25 C/3.3 V cell |
| Google GF180 7T | `43beb45e4d323a76239de436db2df6732e9a689b` | inv_1/dffq_1 FF temperature endpoint JSON |
| ORFS | `cab543eb3508039715a90f402a517852218b5e8f` | full GF180 core libraries |

The JSON renderer preserves units, thresholds, tables and conditions. Its
SKY130 TT result reproduces the pre-existing full Liberty result to report
precision. Per-instance cold/hot endpoint results reproduce the corresponding
whole-library STA results (tolerance 1e-5 ns). No downloaded PDK is redistributed.

## PVT coverage

The matrix is the Cartesian product of these **available core library points**:

| SKY130 HD | GF180 MCU7T5V0 |
| --- | --- |
| TT, 25 C, 1.80 V | TT, 25 C, 1.80 V |
| TT, 100 C, 1.80 V | FF, -40 C, 1.98 V |
| FF, -40 C, 1.65 V | FF, 125 C, 1.98 V |
| FF, 100 C, 1.65 V | SS, -40 C, 1.62 V |
| SS, 100 C, 1.60 V | SS, 125 C, 1.62 V |

All 25 requested pairs produce setup/hold paths without reported electrical
limit violations. At 20 ns, setup ranges from 6.401045 to 9.130081 ns; hold from
8.728909 to 10.343660 ns. These are ideal-internal-wire core-cell harnesses.
Different core supply voltages do not establish a physically valid interface.
This finite matrix omits other process/voltage/temperature combinations, pad
corners, variation, jitter and SI; it is not “full PVT”.

## Real pad case: rejected

The 3.3 V case includes both SKY130 TX pads, both GF180 in_c RX pads, real
receiver/core cells, data and clock SPEF, and explicit static pad controls.
SKY130 DM=110, SLOW=0 selects fast push-pull; output enable is active, input
and analog paths are disabled, and GF180 pull controls are off. GF180 core is
3.3 V in this case. Pin capacitances come from Liberty; SPEF owns wire C only.
OpenSTA reports 1.117215 pF TX pad capacitance, about 3.135837 pF RX capacitance
and 1.035940 pF wire capacitance per net.

The receive-pad transition is about **1.84 ns**, exceeding **1.00 ns** on both
data and clock. The evaluator rejects the result; accepted slack is unavailable.
The regression expects this rejection, not a functional-link pass. Changing
the period cannot cure a slew violation. No library limit was relaxed.

An earlier smoke test exposed two implementation problems that were repaired:
the mode pins must be connected as the `DM` bus, and OpenSTA prints `max slew`
with a space. The previous parser only matched underscore spellings. Regression
tests now reject both spellings, warnings and missing annotations, while still
allowing a legitimate negative timing slack result.

## Local temperature coupling

The CLI profile uses SKY130 **FF/1.65 V, -40 to 100 C** and GF180
**FF/1.98 V, -40 to 125 C**. Each instance receives a distinct cell/library
name and its own sampled temperature. Source coordinates and chiplet rotation
are recorded. Example coordinates are synthetic, not placed-cell extraction.

For the layered 3 W case, TX register/data/clock temperatures are
60.414996/59.513274/59.459465 C; RX clock/register are 57.497226/57.460649 C.
The resulting setup/hold is **8.969588/9.952722 ns**. This is a model prediction,
not a validated physical link. Package R stays at its reference temperature.

Interpolation matches repeated groups by symbolic conditions, handles changed
load axes using their common domain, and forbids temperature extrapolation or
mixing process/voltage endpoints. Limits are conservative between endpoints.
It changes actual delay, slew, capacitance and sequential constraint data;
changing only nominal temperature is not used as a substitute.

| Temperature control | Setup ns | Hold ns |
| --- | --- | --- |
| All core instances 60 C | 8.968843 | 9.952336 |
| Only TX data buffer 100 C | 9.031549 | 9.978516 |
| Only TX clock buffer 100 C | 8.992469 | 9.928816 |
| Only RX register 100 C | 8.931949 | 9.955244 |

The first integration run failed an assumption that data-side and clock-side
heating must have opposite setup effects. That expectation is retained as a
rejected hypothesis. At the actual operating point, data rise delay decreases
with temperature, while falling forwarded-clock delay increases. Both improve
setup. The data buffer's rise delay changes from 1.059608340 to 0.997630000 ns;
its input capacitance also changes the launch-register delay. An independent
query of the original endpoint tables at OpenSTA's reported input slew/Ceff
matches within **7.51e-8 ns**. This is numerical agreement, not evidence that
linear temperature interpolation is physically accurate.

## Gates and remaining work

The 29 unit tests, original two-chiplet CLI, MFIT package comparison, passive
ngspice comparison, existing core timing controls and new characterization
checks pass. The pad failure remains visible and the failed initial hypothesis
is not deleted. See the compact receipt for individual checks and source hashes.

Still incomplete: measured package calibration; an electrically qualified
pad/PHY design; full application-specific PVT/variation coverage; independent
SPICE temperature holdouts; local pad temperature characterization; package
metal temperature coefficients; extracted high-speed channels, jitter/eye/BER;
RTL workload power and floorplanning search. No physical signoff flag is set.

Reproduce using the commands in the README. `qualification` always separates
these physical evidence gaps from numerical/software success.
