# v0.5: independent die boundaries, open cases and layout ranking

This milestone fixes a real lateral-conduction defect and runs a predeclared
27-candidate comparison. It does **not** complete package signoff, hot-pad
characterization, generic multi-chiplet timing graphs or floorplanning search.
No measured package/sample data are available. The source and thresholds are
recorded in [the plan](validation-plan-v05.md), [source lock](../tools/sources.lock.json)
and [compact receipt](evidence/v05-validation.json).

## Production changes

Chiplet-only layers retain per-cell die identity. Touching independent dies
have adiabatic sidewalls unless a pair contact is explicitly supplied. Shared
package layers still conduct normally. Independent analytic controls cover
zero gap, 10 nm gap, 1 mm gap, finite contact resistance and different material
conductivities in both lateral directions. Offset rectangular layer footprints
and per-die conductivity are supported on a **common z stack**. Per-die thickness,
per-die vertical interface resistance and rotated material tensors are not.

`layout.place_design()` moves a fixed design and rebuilds data/clock routes
independently; `layout.evaluate_layout()` evaluates in memory. Default outputs
explicitly lack timing until the STA harness is called. Declared corridors are
ideal rectilinear routes without routing-layer assignment, spacing, obstacles,
SI or DRC. No SA or other optimizer is added.

Validation adapters now live under `tools/validation/`, outside production
modules. The existing MFIT control reuses this adapter rather than maintaining
a second implementation. Downloaded sources/models remain in ignored `local/`;
exploratory duplicate downloads were removed. Logs, generated cases, negative
controls and detailed results remain in ignored `results/`.

## Independent evidence scopes

| Source | Executed cases | Result | What it establishes |
| --- | --- | --- | --- |
| MFIT | Original homogeneous, spatially subdivided homogeneous, heterogeneous geometry/power configurations | 3 passed | Identical remeshed steady networks, conservative power and XY convergence |
| RapidChiplet | Original 16-chiplet, 24-link example | Passed | Placement/PHY coordinate conversion and identical upstream Manhattan lengths |
| PULP serial_link | Unchanged SDR PHY, 1-bit/div8 and 8-bit/div12; late-data control | 2 positive + 1 expected failure | Exact 128-word transport, gating, bounded backpressure; mismatch detection |
| OpenSTA | Original SDF, min/max Liberty, SPEF examples | 3 exact report matches | Engine regression for one upstream design with three annotation modes |

These are four source families, **not four physically qualified D2D designs**.
PULP RTL has not been mapped to the separate GF180/SKY130 GPIO STA netlist.
The original negative SKY130-TX/GF180-RX pad direction remains rejected.

Pinned sources:

- [MFIT](https://github.com/AlishKanani/MFIT/tree/4444336d95fe7e9a3bf440c96937831126c6a37f): GPL-3.0 license file retained locally.
- [RapidChiplet](https://github.com/spcl/rapidchiplet/tree/17176f92c91eda629a25bc11bf7959d6b963a23b): local reference downloads only; no upstream source or input redistribution here. No license grant is inferred.
- [serial_link](https://github.com/pulp-platform/serial_link/tree/521908b92919ac143cbc489623d2300f17589c52): SHL-0.51; dependency pins come from its `Bender.lock`. Common-cell files include SHL-0.51 and Apache-2.0 notices; their original headers/licenses are retained.
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA/tree/02b129d48fbefb57d08f4bc412700ddfa24a159b): original license retained with reference downloads and golden-run artifacts.

## Thermal results and retained failures

MFIT cases preserve the source package geometry, offset C4/interposer footprint,
anisotropic substrate/C4 conductivities, boundary conditions and declared block
power. Each block uses `max_power * mean(all supplied percentages) / 100`.
Samples are equally weighted; no physical duration or measured power is inferred.
This is a steady mean-power experiment, **not replay of the transient trace**.

Reference assembly executes unchanged hash-verified MFIT Python methods, without
its native transient binary; NumPy solves the dense steady system. Comparison
uses a matched 0.5 mm XY grid, followed by refinement of our solver. Original
MFIT per-layer/nonuniform meshes are not claimed reproduced.

| MFIT case | Dies / blocks | Mean power W | Reference nodes | Maximum same-network temperature difference K | Fine peak °C | Final peak / block-mean change K |
| --- | --- | --- | --- | --- | --- | --- |
| Homogeneous | 4 / 4 | 6.024 | 1794 | 5.37e-12 | 80.10635 | 0.02646 / 0.03155 |
| Spatial tiles, TX/RX | 4 / 80 | 9.897057 | 1794 | 8.97e-12 | 115.82200 | 0.03376 / 0.07915 |
| Heterogeneous | 3 / 3 | 6.2878 | 1821 | 5.20e-12 | 81.47024 | 0.02020 / 0.02848 |

The second case initially failed the **0.1 K block-mean gate** on uniform
76→152 refinement: 0.12714 K. That failure remains in the receipt. Aligning mesh
edges with the power blocks and refining requested 76→114→152 (final actual
160×160 XY) reduces the last block-mean change to 0.07915 K. Thresholds were not
relaxed. Refinement differences are diagnostics, not rigorous error bounds;
z discretization and physical model error remain separate limitations.

The initial MFIT adapter also exposed a floating-point boundary issue: Python
3.12's improved `sum()` and iterative layer-z addition yielded different final
bits. Upstream MFIT compares top-z and package height using exact equality, so
its top convection disappeared. The adapter now derives both from the same
accumulation; source methods and thicknesses remain unchanged. Boundary sink
conductance is explicitly compared (maximum difference 2.78e-16 W/K). The
incorrect first-run temperatures are retained only as a failed adapter control.

RapidChiplet retains the original dimensions, positions, 20.5 W per die and
PHY endpoints. All 24 link lengths match the unchanged upstream geometry
routine. Its **328 W** thermal evaluation adds our explicitly assumed stack and
convection because RapidChiplet supplies no thermal ground truth. The resulting
peak is **285.58724°C**: a high-temperature consequence of those assumptions,
not evidence of an acceptable package or valid PDK operating condition. It is
not sent into the GPIO or local-temperature timing model. Final XY peak and
block-mean changes are 0.000453 K and 0.000583 K.

## RTL and STA evidence

Verilator 5.020 executes the original PULP TX/RX and gray FIFO dependencies.
The TX base clock is 10 ns, local RX clock 13 ns; the ideal digital data and
forwarded-clock channels each delay by 2 ns. Tests include clock-gated idle
periods and bounded RX backpressure, checking count, order and value. A separate
90 ns data-delay control must fail with `DATA_MISMATCH`. FIFO overflow and
simulation timeout also fail, rather than becoming successful completion.
Only upstream missing-timescale warnings are suppressed; other compile
warnings are fatal. Assertions are enabled. No upstream RTL is patched.

No AXI/serializer/DDR coverage, metastability probability, pad waveform,
S-parameter, BER or PDK implementation evidence follows from this simulation.
OpenSTA golden cases use the original example libraries, not foundry PDKs;
SDF and SPEF each report one path, min/max reports two. Reports match original
upstream goldens exactly after removal of the tool banner.

## 27-candidate ranking experiment

Design, power (3 W), package, orientation, TT25 GPIO models and 20 ns period are
fixed. Only TX `(x,y)` and RX `x` vary as declared in the plan. Data uses y=1.5 mm
and clock y=4.5 mm corridors. The actual STA includes both routes' RC. Meshes
are requested 48×32 and 96×64, with geometry-conformal subdivisions.

- 27 candidates are geometrically legal; **20** pass electrical and setup/hold
  checks. **7** electrical failures retain full OpenSTA logs and rejection files.
- Largest final peak-temperature mesh change: **0.012534 K**; no accepted pair changes thermal order between the two meshes.
- **121** accepted candidate pairs have opposing thermal/timing preferences
  larger than the final mesh-change proxy and conservative printed slack
  precision. This is numerical separation only; model error is unknown.
- Thermal-only chooses `layout_26`. Timing-only has `layout_00`, `layout_12`,
  `layout_24` indistinguishable at report precision; no unique timing winner is
  claimed. The primary equal-weight score chooses `layout_24`.
- Joint thermal weights 0.25, 0.50, 0.75 choose `layout_24`, `layout_24`,
  `layout_25`. Weights are predeclared, not tuned to create disagreement.

Representative candidates:

| Candidate | TX (x,y) mm | RX (x,y) mm | Peak °C | Setup ns | Hold ns |
| --- | --- | --- | --- | --- | --- |
| 00 | (0.5,1) | (6,2) | 61.95085 | 8.771576 | 10.940630 |
| 12 | (1.5,1) | (7,2) | 60.92454 | 8.771576 | 10.940630 |
| 24 | (2.5,1) | (8,2) | 60.38618 | 8.771576 | 10.940630 |
| 25 | (2.5,2) | (8,2) | 59.91633 | 8.705307 | 11.004650 |
| 26 | (2.5,3) | (8,2) | 59.74904 | 8.639044 | 11.069210 |

The normalized joint score is
`w * (peak_C - 25)/10 - (1-w) * min(setup_ns, hold_ns)/1`.
The final mesh-change proxy and report precision define numerical tie groups;
these are not confidence intervals for physical performance.

Independent route-length controls at a fixed layout:

| Change from 3 mm data + 3 mm clock | Setup ns | Hold ns |
| --- | --- | --- |
| Nominal | 8.705309 | 11.008110 |
| Only data +1 mm | 8.673013 | 11.038710 |
| Only clock +1 mm | 8.737604 | 10.975820 |
| Both +1 mm | 8.705309 | 11.006420 |
| Only data +2 mm | 8.639642 | 11.069790 |
| Only clock +2 mm | 8.770976 | 10.942450 |
| Both +2 mm | 8.705311 | 11.004120 |

The +4/+8/+12 mm controls are rejected by electrical checks. Longer routes must
not be compared using unconstrained extrapolated timing. Changes in receiver
slew/constraints mean hold does not cancel exactly even with paired routes.

**Gate decision:** placement changes thermal and constant-temperature timing
preferences within these models. It does not yet demonstrate a physical
thermal-aware D2D timing advantage: the TT GPIO pads lack validated temperature
characterization, the core-only FF interpolation is a different design, channel
RC is assumed, and physical error has no bound. Keep search deferred. The next
technical gate is one consistent interface characterized at fixed process and
voltage across temperature, with independent waveform checks and holdout points.

## Reproduction and regression

Use a new directory for each run:

```bash
python -m pip install -e '.[validation]'
python tools/bootstrap_validation.py --build-sta
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two-chiplets
python tools/validate_package.py --output results/package
python tools/validate_electrical.py --ngspice /path/to/ngspice --output results/electrical
python tools/validate_characterization.py --output results/characterization
python tools/validate_prototype.py --output results/prototype
OPENBLAS_NUM_THREADS=1 python tools/validate_open_thermal.py --output results/open-thermal
python tools/validate_sta_goldens.py --output results/sta-goldens
python tools/validate_pulp_phy.py --verilator /path/to/verilator --output results/pulp-phy
OPENBLAS_NUM_THREADS=1 python tools/validate_layout_ranking.py --output results/ranking
```

47 unit tests pass. Prior package, nine electrical, eighteen characterization
(including 25 core PVT combinations), and sixteen prototype software checks
remain passing. New external runners are included in CI. Compact evidence is
tracked; raw logs/models, environments and downloaded upstream assets are not.
