# Local multicase contract bridge — pre-run plan, 2026-11-11

Base c124aa9; fetch succeeded and origin/main matched before this session.
User requested local-only experiments. No push or remote CI is part of this run.

## Questions and fixed acceptance criteria

1. Does the declared opposite-edge contract select the intended rise/fall data
   and clock paths in real core/IO libraries? Check all four setup/hold × data
   rise/fall paths; clock source fall, buffer/pad fall, receiver inverter rise,
   and receiving FF positive edge must match the explicit netlist contract.
2. Do receiver setup/hold numbers match direct interpolation of the loaded
   Liberty constraint tables, using the table's declared axis order and the
   reported data/clock slews? Do not assume identical axis order between PDKs.
   Identify arcs by type/pin, never by fitting observed slack. Tolerance 1e-5 ns.
3. Reconstruct arrivals from path increments and required time from ideal event,
   observed clock propagation, independently looked-up receiver constraint and
   declared uncertainty. Tolerance 1e-5 ns. This uses STA propagation increments
   and is an accounting/contract bridge, NOT an independent channel-delay oracle.
4. Report every table-domain excursion separately. A numerically matching
   extrapolation does not qualify a path. Preserve negative timing slack as a
   legitimate analysis result; preserve electrical/model rejection separately.

## Frozen case families

- Core harness: the existing 5 SKY × 5 GF characterized points (25 combinations),
  original TT equivalence, cold/hot endpoints, uniform 60 C, isolated TX-data,
  TX-clock or RX-register heating, and coupled local temperatures. These are
  variations of ONE core netlist, with no physically qualified cross-voltage IO.
- GF180-to-SKY130 GPIO: matched straight routes 0.1, 1, 3, 6 and 12 mm;
  default 20 ns period with 50% duty. The 12 mm case is the known electrical
  failure control. Also fixed 3 mm with 40%/60% duty, 40 ns period, diagnostic
  setup/hold uncertainty 0.1/0.05 ns, and deliberate 2 ns setup failure.
  These assumptions test semantics; they are NOT workload-derived requirements.
  Retain the original SKY-to-GF direction as an electrical failure control.
- Thermal: three original MFIT input cases with numerical-reference comparison,
  and RapidChiplet's 16-die geometry with an explicitly assumed stack. The latter
  has no admitted timing constraints and must not receive fabricated STA results.

## Error controls and reporting

For an otherwise valid GPIO record, require rejection of wrong inversion,
missing generated clock, wrong capture endpoint, missing output constraint and
wrong clock uncertainty. Also test constraint-axis swapping on asymmetric data.
Include raw reports, immutable input hashes, loaded-library hashes, executable
hash and analyzed commit. List failed or out-of-domain cases, not only successes.
No failure-based retuning of frequency, thresholds, PDK data or cooling inputs.
No optimizer or physical-signoff claim. Prior pad SPICE disagreement remains open.

Before the complete propagation-table pass: extend bounded-domain diagnostics to
all active core propagation cells, not just receiver constraints and GPIO pads.
Query original NLDM delay/slew tables at STA-reported slew/Ceff and compare the
used arc delay with each expanded path. Keep the same 1e-5 ns numeric tolerance.
Ceff and input slew are engine-derived; this is a conditional source-table
consistency check, not an independent validation of the channel or DMP solver.
Do not equate driver NLDM slew with the RC-distorted propagated output slew.
