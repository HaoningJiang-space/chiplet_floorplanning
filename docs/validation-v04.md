# v0.4 geometry and low-speed GPIO prototype

Validated on 2026-11-11 with the pinned OpenSTA 2.2.0 build and hash-locked
public PDK inputs. This is software/model validation, not a manufactured-link
or package signoff result. Raw runs remain under ignored `results/`.

## Executed checks

- 38 unit tests, original two-chiplet CLI and the new GPIO CLI.
- `tools/validate_prototype.py`: 16 software gates, including expected failures.
- Previous MFIT, core electrical/passive-ngspice and 25-pair core-PVT/temperature
  checks all pass. Existing aligned-layout peak remains 60.747302853 C.
- MFIT matched-network temperature difference: 1.414e-12 K; this is agreement
  of equations, not temperature accuracy against a real sample.
- Anisotropic conduction plus contact resistance agrees with an independent
  series-column solution within the predeclared 1e-7 K numerical tolerance.
  Rotated, non-grid-aligned die islands conserve area and power and retain
  reciprocal face conductances.

## Prototype design and timing

The electrical direction is intentionally **GF180 TX -> SKY130 RX**, with both
I/O domains at 3.3 V, GF core at 3.3 V and SKY core at 1.8 V. It is a single
source-synchronous SDR lane with rising-edge launch and falling-edge capture,
TT/25 C, a 50% duty-cycle ideal clock, zero clock uncertainty and zero internal
wire parasitics. These last two settings are assumptions, not measured jitter
or extracted physical implementation.

GF `bi_t` uses its documented 16 mA fast mode, while SKY `gpiov2_pad` uses its
CMOS input-only mode. Receiver `buf_16` and `inv_8` are actual PDK cells. Smaller
loads fell below the pad table's minimum 0.01 pF: the receiver buffers are a
real netlist design change to stay within the source table domain, not a change
to PDK data or a fictitious load. Exact mode controls and source links are in
`timing.interface` and `src/chiplet_floorplanning/interfaces.py`.

| Case | Setup ns | Hold ns | Decision |
| --- | ---: | ---: | --- |
| 20 ns period, 3 mm declared straight route | 8.705309 | 11.008110 | Declared checks pass |
| 40 ns period, same route | 18.705310 | 21.008110 | Half-period margin increase |
| 2 ns period, same route | -0.2946914 | 2.008112 | Setup fails; result retained |
| 20 ns, 0.01 mm | 8.705316 | 11.024440 | Declared checks pass |
| 20 ns, 0.1 mm | 8.705314 | 11.013600 | Declared checks pass |
| 20 ns, 1 mm | 8.705314 | 11.011650 | Declared checks pass |
| 20 ns, 6 mm | 8.705307 | 11.002450 | Declared checks pass |
| 20 ns, 12 mm | — | — | Electrical limits violated |
| Original SKY TX -> GF RX, 3 mm | — | — | RX slew 1.84 ns > 1 ns |
| New direction, small receiver buffer | — | — | Pad load below table domain |

There is no conclusion that a 12 mm physical link is impossible, or that all
lengths below 6 mm are qualified. These are discrete cases of the declared
constant-section RC model and fixed cells. Data and clock lengths track each
other, so much of their delay cancels in slack; setup need not decrease strongly
with common wire length. No timing limit has been weakened to accept a case.

All four pad arcs, rise/fall and min/max, pass 16 independent lookups of original
PDK delay/slew tables. Maximum nominal table-lookup discrepancy is
2.618e-7 ns. This verifies table interpolation at STA-provided slew/Ceff; it is
not an independent validation of the Ceff algorithm or transistor waveforms.
Core constraints outside these pad checks do not gain a table-domain guarantee.

The pinned `report_dcalc` traverses both input and output vertices of bidirectional
pins, including inactive arcs. Diagnostics explicitly select the input vertex
at the receiving PAD, then match the configured active mode's source tables.
The receiver's disabled driver vertex must not supply a zero-slew witness.
Eight actual pad arcs in expanded setup/hold paths are also checked against
those configured-mode delay tables. Capture-clock min/max is opposite to the
data-path min/max. TX table slew and propagated driver slew are recorded
separately: the pinned engine's
[DmpPi::gateDelaySlew](https://github.com/The-OpenROAD-Project/OpenSTA/blob/02b129d48fbefb57d08f4bc412700ddfa24a159b/dcalc/DmpCeff.cc)
uses an RC waveform estimate for driver slew, while its diagnostic prints the
NLDM table slew at Ceff. Comparing those as identical quantities would be an
incorrect validation test. Electrical limits are checked on propagated slew.

The first v0.4 sweep rejected the 0.01 mm wire because subtracting large pin and
total capacitances in OpenSTA float arithmetic produced 0.003452967 pF instead
of SPEF's 0.003453133247 pF. The readback tolerance now derives from four float32
relative epsilons of total capacitance; zero and unresolvably small annotations
still fail. `results/v04-prototype-01` retains that failed run;
`results/v04-prototype-02` passes after the precision fix;
`results/v04-prototype-04` also includes expanded-path witnesses and the final code organization. Library limits and
original source tables were unchanged.

## Mesh and local-temperature convergence

The mesh now follows actual die and block boundaries. A 0.137 mm translation is
legal and does not snap the die. `nx,ny` are pitch targets; actual cell counts
are recorded. Temperature uses die-restricted bilinear reconstruction, with
explicit clamping near die boundaries. This replaces the old piecewise-constant
containing-cell sample, which could change nonmonotonically under refinement.

The following convergence results use the existing FF **core-only** temperature
profile, separately from the TT pad prototype:

| Layout | Requested grids | Actual final grid | Final max instance change K | Final max slack change ps |
| --- | --- | --- | ---: | ---: |
| Aligned | 24x16, 48x32, 96x64 | 96x64 | 0.0155322 | 0.032 |
| TX shifted +0.137 mm | same | 97x64 | 0.0151615 | 0.027 |

Both pass the predeclared 0.1 K / 1 ps final-change gates. This is a convergence
check for these samples and the current z discretization, not a global error
bound or a physically calibrated local junction temperature.

## Reproduction and remaining evidence

Follow the low-speed command in the README, then run:

```bash
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/v04-basic
python tools/validate_package.py --output results/v04-package
python tools/validate_electrical.py --ngspice /path/to/ngspice --output results/v04-electrical
python tools/validate_characterization.py --output results/v04-characterization
python tools/validate_prototype.py --output results/v04-prototype
```

The new validation is included in CI; generated PDK-derived `.lib` files are
excluded from its uploaded results. No PDK source assets are committed.

Still missing: measured package/thermal/channel calibration; extracted internal
and package parasitics; transistor-level pad waveforms and DC noise margins;
complete pad PVT; pad-temperature characterization and independent temperature
holdouts; a full protocol/gate-level functional simulation; jitter, coupling,
inductance, eye and BER qualification. The user has no physical sample data.
The tool continues to report `complete_package_signoff: false` and does not
claim that the TT pad lane has been thermally qualified.
