# Complete core-fabric transistor comparison

At the user's revised decision-focused acceptance, the next useful comparison
is a complete data/clock path. Isolated-cell errors cannot simply be summed:
clock/data discrepancies can partly cancel, while setup and hold respond with
opposite signs. This stage keeps the complete shared circuit rather than
substituting independent ideal ramps at each routed net.

## Contract

The nominal thermal-minimum witness's verified 25 C reference receipt supplies
the actual 32-cell Verilog fabric and all nine routed RC networks. All eight
data lanes, two TX banks, both receiver branches, and the single shared clock
root/trunk remain present. The three pinned public transistor cell views are
the previously diagnosed `buf_8`, `inv_1` and `dfxtp_1`, at TT/1.8 V/25 C.
Conductor and extra shunt capacitance appear once; Liberty receiver pin C is
not added to a receiver already represented by its transistors. Each output
has the same 0.01 pF external load as the saved STA script.

The root clock has the original 20 ns period and 0.1 ns 20–80% slew. Data
uses the same slew; all lanes first capture zero, then one, then zero with
data transitions comfortably before launch. Ideal shared supply and uncoupled
RC remain assumptions. Two 60 ns simulations use maximum steps 5/2.5 ps.
The matched reference includes the input ramp's 50% crossing offset.

This is a **cross-model comparison**, not an identity claim about the original
Liberty characterization PEX or primitive models. It does not include real
Pad/ESD, package inductance/coupling, supply droop, jitter or temperature feedback.
No setup/hold characterization criterion is fitted or inferred from successful
logical capture.

## Result

All eight lanes captured both transitions at both time steps. Independent replay
of 32 path observations verifies saved waveform hashes, source receipt identity,
unique crossings and captured rail values. On the finer step:

| Quantity | Observed result |
|---|---:|
| Minimum available setup window | 9.869279316 ns |
| Minimum available hold window | 9.939718470 ns |
| SPICE minus STA available setup window | +82.974471 to +113.159707 ps |
| SPICE minus STA available hold window | -113.105783 to -83.091512 ps |
| Maximum window change when step is halved | 0.124029 ps |

Available setup time is `capture_next - data_arrival`; available hold time is
`data_arrival - capture_previous`. **Neither is slack**: receiver setup/hold
requirements have not been independently characterized in this experiment.
The two margins must not be conflated, and logical capture of these patterns
does not certify all possible data histories or metastability behavior.

The observed window discrepancy is much larger than the tested time-step
variation. Further reducing that variation is not a priority. The discrepancy
does not prove a simulator bug and is not a deterministic physical error bound.
The full-path experiment supports a nominal wide-window mechanism result; it
does not yet establish a robust physical optimum or qualify electrothermal
feasibility across all layouts and workloads.

## Reproduction and next gate

```powershell
. ./tools/windows_env.ps1
python tools/audit_integrated_transistors.py results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness/reference --output results/fabric-transistors
python tools/summarize_integrated_transistors.py results/fabric-transistors results/physical-calibration/integrated-witness-v1/nominal_slot1_rot180_witness/reference --output results/fabric-transistors-summary.json
```

The runner explicitly requires the pinned netlists from the earlier core
diagnostic runs. Raw traces remain local; [compact evidence](evidence/local-integrated-transistors.json)
contains per-lane windows and all artifact hashes. Translator negative controls
cover missing cell identity, nonpassive R and duplicate counting of pin loads.
The full project suite passed 201 tests and the documented two-chiplet CLI ran.

Next extend the common-reference comparison to the declared temperature field
and receiver constraint behavior. Preserve this nominal baseline and its model
differences; do not replace STA values by fitted offsets or call an observed
maximum discrepancy a universal uncertainty bound.

## GitHub Chat review and local corrections

The Chat review at `6f8f49c` enumerated 53 reachable commits, obtained all nine
new patches after `171c5e9`, and read the principal HEAD sources/evidence. The
previous 44 commits relied on earlier review; raw local waveforms and tests
were not independently rerun. It confirmed window signs/reference edges and
the distinction between windows and slack. Its three new findings were:

1. Missing receipt RC could silently fall back to an ideal Verilog connection.
   The generator and replay now require the exact eight data nets plus shared
   clock, exact source/sink terminals tied to Verilog, valid RC node indices and
   finite passive values. Re-exported coefficients/terminals/units must match
   the independently hash-verified saved SPEF. Missing data/clock nets, changed
   capacitance and wrong terminals have negative tests.
2. HiTS completion could be true with a rejected solve. Its tool now separates
   `execution_complete`, `all_solvers_accepted` and successful `complete`, and
   exits with an error if any expected solve is missing or rejected. Synthetic
   rejection and incomplete-domain tests exercise those cases. All three
   original saved solves were accepted; the original evidence is retained.
3. The observation list repeated `clk`. New generation deduplicates the entire
   list. Both original raw files were checked: the two old clock columns are
   exactly equal. Existing traces remain unchanged and replay with their own
   recorded column lists.

The strengthened replay additionally requires exactly one receiver Q threshold
transition in each expected event window, occurring after the capture clock,
alongside the existing stable-level check. All 32 observations pass; this
improves capture evidence without characterizing setup/hold or metastability.
The [reviewed replay](evidence/local-integrated-transistors-reviewed.json)
has unchanged window metrics and retains the original raw report hash.
The local correction suite passed 204 tests and the documented CLI case.
These corrections are locally verified; the external review itself covers
`6f8f49c`, not the subsequent correction commit.

The next decision experiment should compare paired layouts with identical
stimuli and models, testing whether SPICE and STA agree on the **difference**
in setup/hold windows. This directly addresses ranking sensitivity before
investing in more isolated-cell or solver residual refinement.
