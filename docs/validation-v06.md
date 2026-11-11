# v0.6 — same-interface transistor diagnostics

The GF180 TX -> SKY130 RX pad modes now run in transistor-level ngspice
diagnostics. **The nominal SPICE/Liberty agreement gate fails. No hot-pad
Liberty is released, and these results are not connected to production STA.**
The TT GPIO prototype and the separate core-only temperature harness remain
distinct. There are still no measured package or silicon samples.

The [plan](validation-plan-v06.md) fixes numerical and model-agreement
tolerances. [Compact evidence](evidence/v06-validation.json) preserves source
hashes, conditions, measurements, failed gates and regressions. Raw decks,
models and waveforms remain under ignored `local/` and `results/` directories.

## Sources, topology and electrical stimulus

| Input | Locked source |
| --- | --- |
| GF180 `bi_t` CDL | `google/globalfoundries-pdk-libs-gf180mcu_fd_io`, `2aeec51ea2824b6cc0b396acfc39f4535f40b23a` |
| GF180 device models | `efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr`, `aacc04cc30ed119baaa616dff266cca7006dc3d6` |
| Upstream CDL syntax filter | `RTimothyEdwards/open_pdks`, `5740c4a81c42f9fe4af5ef2ee258a99151053d28` |
| SKY130 built IO and primitive SPICE | Volare `sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392`, `sky130A` |
| Nominal Liberty | Existing `tools/sources.lock.json`, unchanged |

Exact download URLs and SHA-256 hashes are in
[`tools/spice-sources.lock.json`](../tools/spice-sources.lock.json).
Only the required SPICE directories, source/license metadata and one matched
SKY TT Liberty are extracted. Existing files are verified against the original
archives on every run. No third-party model is redistributed in this repository.

GF180's original CDL has 182 MOS, 12 resistor, 2 capacitor and 14 diode
instances. The pinned upstream filter changes CDL syntax to SPICE wrappers;
the audit requires all **210 elements**, nodes and parameter values to survive
the declared transformations. It does not infer timing fidelity from LVS
connectivity. The [upstream issue](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_io/issues/11)
documents this CDL/model compatibility problem.

The controls come from the same `interfaces.py` definitions as the TT STA
prototype. Pin order comes from the SPICE wrapper. Every control's high rail is
checked against its Liberty power/signal-level attribute; unknown pins are
rejected. GF180 core/IO supplies are 3.3 V. SKY130 core/hibernation supplies are
1.8 V and its IO/analog/switch supplies are 3.3 V. Unused pad outputs remain
separate open nodes. No output is shorted to a supply to obtain convergence.

Inputs are ideal, noninverting 0–3.3 V linear ramps starting at 10 and 40 ns;
each independent transient ends at 70 ns. Delay uses 50% crossings, separately
normalized to input/output supplies. GF slew is 10–90%, SKY slew is 20–80%.
There is no package, core FF, jitter or clock path in this isolated-pad test.
Model Monte Carlo switches are disabled; process and supply do not change with
temperature. GF model documentation describes extraction at -40, 25 and 125 C;
our 0–125 C sweep remains a diagnostic of those models, not new measured pad
qualification. [GF model extraction](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_2_1.html)

**Load convention:** SPICE gets only the declared external capacitor. It already
contains the transistor circuit's intrinsic capacitance. GF Liberty's timing
axis starts at its declared inout pin capacitance, 2.977816 pF, while its power
axis starts at zero. We compare against the existing STA convention
`C_axis = C_external + 2.977816 pF`; we do not add this constant capacitor to
SPICE. This mapping is supported by those axes and the STA net loading, but the
original characterization deck has not been recovered. It remains an explicit
assumption. SKY's receiving `IN` output uses the external load directly.

## What passed numerically

All **14** transient cases completed and passed the stated settled-rail and
single-crossing checks. These checks do not qualify overshoot, ESD or safe
operating area. Output minima/maxima are retained separately.

- Half-step comparison at GF 25/125 C and SKY 25 C: largest metric change
  **0.3954 ps**, below `max(2 ps, 0.5%)`.
- GF endpoint interpolation at 0/125 C, checked against held-out 25/50/75/100 C:
  largest error **6.026 ps**, maximum relative error **0.298%**; all pass
  `max(5 ps, 2%)`.
- **55 unit tests**, the original two-chiplet CLI and **16 prior prototype
  software checks** pass. The TT lane still reports setup **8.705309 ns** and
  hold **11.008110 ns**; it has not consumed the experimental SPICE data.

GF diagnostic response with a 0.5 ns input slew and 6 pF external load:

| Temperature C | Rise delay ns | Fall delay ns | Rise slew ns | Fall slew ns |
| --- | --- | --- | --- | --- |
| 0 | 2.419541 | 2.579094 | 0.851486 | 0.733500 |
| 25 | 2.577164 | 2.749404 | 0.921208 | 0.799016 |
| 50 | 2.733556 | 2.918502 | 0.990117 | 0.865329 |
| 75 | 2.888276 | 3.085884 | 1.058271 | 0.932170 |
| 100 | 3.040947 | 3.251097 | 1.125224 | 0.999317 |
| 125 | 3.191203 | 3.413701 | 1.190885 | 1.066543 |

These are conditional model responses. The 6/12 pF diagnostic cases are not
declared electrically legal links. In particular, a table being in range does
not imply its predicted slew meets the library's electrical limit. The report
keeps nominal output-slew checks separate from waveform measurement accuracy;
25 C limits are not silently promoted to temperature-qualified limits.

## What failed and why integration stays disabled

At 25 C, the agreement tolerance is `max(20 ps, 10%)` for each delay/slew.

| Case | SPICE rise/fall delay ns | Liberty rise/fall delay ns | Result |
| --- | --- | --- | --- |
| GF, 0.5 ns input, 2 pF external | 2.367657 / 2.542253 | 2.891168 / 3.102224 | Fail; both measured and table output slews are below the nominal 1 ns limit |
| GF, 0.5 ns input, 6 pF external | 2.577164 / 2.749404 | 3.116259 / 3.337365 | Fail |
| SKY, 1 ns input, 0.022799 pF external | 1.072101 / 1.175055 | 1.400499 / 1.600533 | Fail |

Across the five GF nominal slew/load points, delay disagreement is approximately
**15.9–18.1%**. The SKY delay disagreement is **23.4–26.6%**; slew disagreement
is **55–62%**. No load or timing table was adjusted to make these results agree.
The lower-load GF control shows that the discrepancy is not confined to the
overloaded diagnostic points.

SKY's reachable IO hierarchy includes two empty subcircuits:
`sky130_fd_io__condiode` and `sky130_fd_io__com_pad`. The former is explicitly
an upstream placeholder for a parasitic well/substrate diode. Their behavioral
impact is not quantified, and no substitute was invented. The simulator also
reports an ignored resistor-model expression, multiplier-hierarchy and initial
convergence warnings. GF reports disabled diode IKK behavior. These diagnostics
are preserved; they are not asserted to be the cause of the measured error.

The SKY SPICE build and original Liberty have different revision identifiers.
As a control, all four active receiver tables from the **same Volare archive**
have identical axes and values to the original Liberty (the archive cell is
named `gpiov2_pad_wrapped`). Thus a difference in those tables does not explain
the mismatch. This limited identity does not prove whole-cell or PEX equivalence.

**Decision:** do not derive temperature derates or a replacement Liberty from
these measurements. A complete, traceable pad netlist, device-model setup and
original load/PEX characterization contract must first reconcile nominal
delay/slew. Then repeat the fixed-P/V temperature gate and characterize the
actual active core arcs and setup/hold constraints. Full pad PVT, a physically
qualified hot D2D path, calibrated packaging and SA remain unfinished.

## Reproduction

Use fresh output directories and an installed ngspice (local receipt: version 42).
The SKY deck explicitly uses `ngbehavior=hsa`; initialization is isolated from
user configuration. No global SPICE, PDK, Git or authentication setting changes.

```bash
python -m pip install -e '.[validation]'
python tools/bootstrap_validation.py
python tools/bootstrap_pad_spice.py
python tools/validate_pad_spice.py --ngspice /path/to/ngspice --output results/pad-spice
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two-chiplets
# Requires the OpenSTA build from the main validation instructions:
python tools/validate_prototype.py --output results/prototype
```

The new CI job checks execution, source audits and numerical consistency. Its
successful exit does **not** mean `qualification_gates` passed. Those failures
are retained in the uploaded JSON together with decks, logs and waveforms.
