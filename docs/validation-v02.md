# v0.2 package and real-PDK integration receipt

Validated 2026-11-11. The acceptance thresholds were recorded in
`validation-plan-v02.md` before the integration experiments. All final controls
passed their declared expectations, including the deliberately failing timing
case. This receipt is for numerical models and a real-library core-cell harness.

## Frozen sources

| Resource | Revision / version |
| --- | --- |
| MFIT | `4444336d95fe7e9a3bf440c96937831126c6a37f` |
| OpenSTA | v2.2.0, `02b129d48fbefb57d08f4bc412700ddfa24a159b` |
| OpenROAD flow library snapshot | `cab543eb3508039715a90f402a517852218b5e8f` |
| SKY130 | `sky130_fd_sc_hd__tt_025C_1v80.lib` |
| GF180 | `gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib` |
| ngspice | 42, Ubuntu `42+ds-3build1` |

Exact downloaded file hashes are in `tools/sources.lock.json`. OpenSTA has one
documented CMake compatibility edit: `find_package(SWIG REQUIRED 3.0)` becomes
`find_package(SWIG 3.0 REQUIRED)`. Its timing implementation is unchanged.
Build prerequisites: C++ compiler, CMake, Tcl development headers, zlib,
Flex, Bison and SWIG. OpenSTA's optional CUDD was available in the local build;
the harness uses no conditional pad arcs. Binary hashes are retained per run.

The MFIT reference uses its verified Python classes, loaded without the
unneeded native transient-library initialization. All geometry, resistance and
power methods run unchanged. Its steady matrix is solved independently with
NumPy. This avoids interpreting an extremely long transient step as exact
steady state and does not claim validation of MFIT's native transient solver.

## Package thermal results

Stack: silicon interposer, effective bump islands, silicon die islands, TIM
islands, copper lid. Conductivities come from MFIT's material file; dimensions,
3 W power, 25 C ambient and top h=1000 W/(m² K) are explicit demonstration
assumptions. The bottom and exposed side surfaces are insulated.

| Check | Observed | Acceptance |
| --- | --- | --- |
| Same-grid MFIT node count | 228 | same topology/geometry |
| Max conductance matrix difference | 4.44e-16 W/K | reported diagnostic |
| Max power-vector difference | 0 W | <= 1e-10 W |
| Max node temperature difference | 1.414e-12 K | <= 1e-7 K |
| Reference heat-balance error | 1.94e-13 W | <= 3e-8 W |
| Peak, 24×16 lateral mesh | 60.74730285 C | convergence series |
| Peak, 48×32 lateral mesh | 60.69891582 C | convergence series |
| Peak, 96×64 lateral mesh | 60.69073457 C | convergence series |
| Last refinement peak change | 0.00818125 K | <= 0.25 K |

Unit tests independently verify the uniform vertical-series resistance,
zero-power equilibrium, superposition, stronger cooling, no power in void,
power conservation and rejection of unsupported material boundaries.

## Electrical results

Nominal wire model: a 3 mm rectangular copper conductor with assumed
rho=1.68e-8 ohm m, width=10 um, thickness=1 um, ground-plane spacing=1 um and
epsilon_r=3.9. Each data/clock net has R=5.04 ohm and C=1.035939974 pF.
These are analytical model parameters, not extracted package parasitics.

| Case | Setup slack (ns) | Hold slack (ns) | Expected observation |
| --- | --- | --- | --- |
| Base, period 20 ns | 8.323373 | 9.680498 | both reports exist |
| Data R ×100, fixed C | 8.189611 | 9.895976 | setup down, hold up |
| Clock R ×100, fixed C | 8.556118 | 9.450858 | setup up, hold down |
| Period 24 ns | 10.32337 | 11.6805 | setup increases by 2 ns |
| Period 2 ns | **-0.6766284** | 0.6804982 | setup violation retained |

The R sweeps are causal sensitivity controls, not claims that moving a die
changes R while leaving C fixed. Setup/hold refer to the opposite-edge capture
relationship and actual library constraints. The short-period violation is an
expected negative result and is not hidden with a false path.

Both SPEF wire capacitances are read back and checked. Missing SPEF,
unannotated package nets and an unknown cell are rejected. The final harness
has no reported max-capacitance/max-slew violations. A preliminary buf_4 smoke
case exceeded its library load table and was not accepted; the frozen harness
uses buf_8, whose characterized load range covers this case. No cell table was
edited or fitted. Intra-die wires are explicitly ideal in this harness.

An independent state-space solution and ngspice agree on the passive channel
50% crossing within 0.00048 ps for both nominal and R=120 ohm/C=0.8 pF stress
networks. This is within the printed measurement resolution and far below the
1 ps/1% gate; it is not a claim of sub-femtosecond physical-model accuracy.
The 20–80% slew values agree as well. The source is an imposed normalized ramp,
so this test does not validate transistor-level SKY130/GF180 waveforms.

## Reproduction

```bash
python -m pip install -e '.[validation]'
python tools/bootstrap_validation.py --build-sta
python -m unittest discover -s tests -p '*_unittest.py' -v
python tools/validate_package.py --output results/package-check
python tools/validate_electrical.py --ngspice /path/to/ngspice --output results/electrical-check
```

Each output directory must be new. Generated inputs, full STA clock paths,
SPEF, SPICE decks/logs, reference matrices and source hashes remain under
ignored `results/`. The compact machine-readable receipt is
`docs/evidence/v02-validation.json`. No downloaded PDK or upstream source is
copied into this public repository.

## Evidence limits

Numerical package validation and TT core-cell STA integration are complete for
these cases. Actual package dimensions/material interfaces, pad/ESD/PHY models,
measured thermal calibration, physical D2D electrical compatibility, full PVT
signoff and temperature-dependent cell characterization remain outside this
receipt. The thermal and timing outputs are separate analyses: the 60 C model
temperature is not silently applied to a 25 C Liberty library. POSTsim has not
been integrated because no implementation/API was present in this repository.
