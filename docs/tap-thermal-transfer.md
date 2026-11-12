# TAP thermal input transfer: local evidence and unresolved model difference

This stage follows `3e51586`; origin was fetched and unchanged before work.
The prior bounded fabric experiment remains closed. This work transfers the
full sourced case rather than extending isolated cell characterization.

## Input admission

`tools/prepare_tap_thermal.py` reads the pinned TAP commit `3a3f4e5` through
Git and executes only its original `gen_flp`, `gen_ptrace`, and fill-space helper.
It does not invoke TAP placement, routing, or simulation. All six source layers,
source material mixtures, power allocation and cooling config are retained.
The 50 mm interposer has a 100 mm spreader and 200 mm sink, 318.15 K ambient,
and 0.009 K/W convection resistance. These are published benchmark assumptions,
not measured calibration of an Ascend product.

An input compatibility issue is now explicit: TAP inserts a fixed half-grid
(0.5 mm) outer material border in the bump and chip thermal layers. The earlier
geometry-only domain did not reserve this border. Its Ascend witness has three
border intersections. The original domain/evidence remain intact. A separate
thermal-compatible subset filters expanded footprints against that border and
uses deterministic area-first witness construction, without temperature feedback.
This is a constraint of this source representation, not an asserted physical
routing keepout. Search failure would mean unknown, not proven infeasibility.

Complete Ascend (6 chips, 350 W), micro150 (8 chips, 680 W), and multiGPU
(6 chips, 755 W) inputs were generated. Each six-layer partition passes boundary,
non-overlap and full-area coverage checks, and each source chip retains its power.
Negative tests reject overlap even when summed areas happen to match, missing
coverage and outside rectangles. No layout optimization has been performed.

## What the local solve establishes

The complete Ascend case uses the sourced 64 x 64 grid and eight grid layers
(six input layers plus spreader and sink), followed by twelve package nodes:
32,780 unknowns. HiTS CPU GMRES with unchanged default tolerance agrees with
its HotSpot 7 native reference to 5.414e-5 K maximum. The original-equation
relative residual is 9.999e-11. This is not the accelerated GPU backend.
The source sum is 350 W; boundary heat out is about 349.9998 W. The exported
matrix is symmetric and its off-diagonal entries are negative. These necessary
checks do not establish equivalence to the original TAP thermal model.

## Negative result: HotSpot 6 to 7 is not yet an admitted model transfer

On the exact same generated input, a local HotSpot 6 build at `47b1e83` differs
from the pinned HotSpot 7 native reference by **45.5823 K** on the exported
layer-0 grid. The HotSpot 6 writer emits layer 0 (`LAYER_SI`) even with the
custom layer configuration, so this comparison is explicitly the substrate,
not the chip layer. Its output is rounded to 0.01 K; rounding cannot explain
the observed difference. HiTS's small error against HotSpot 7 is a different
quantity and cannot excuse this failed model transfer.

The sources already establish different heterogeneous neighbor resistance
rules: HotSpot 6 steady detailed-3D macros call `find_res_3D` with one cell's
resistance, while HotSpot 7's exported matrix calls `find_res`, combining
adjacent half-cell resistances (with special bottom-layer handling). This is
not yet a complete causal attribution of the 45.58 K discrepancy; package
connections, node locations, and the native iterative reference also need to
be reconciled. A same-name option and matching input files do not prove the
same discrete model. The next step is to resolve that equation contract with
physical heat-flux continuity, not tune temperatures to force agreement.

Consequently, the computed HotSpot 7 chip-layer peak (~118.898 C) is diagnostic
only, and outputs explicitly mark physical qualification false and model
transfer unestablished. It must not be used to assert TAP replication, physical
thermal feasibility, or layout superiority. No new optimization or expansive
accuracy campaign is justified by this diagnostic.

## Follow-up boundary audit

The [native boundary audit](tap-native-boundary-audit.md) now demonstrates
an external convection term entering an internal material edge in the pinned
HotSpot 7 detailed-3D assembler. Default layout admission is blocked; the
explicit diagnostic flag below permits investigation only.

## Reproduce locally

With the environment/binary described in `hits-local-integration.md`:

```powershell
. ./tools/windows_env.ps1
python tools/prepare_tap_thermal.py --tap local/upstream/TAP-2.5D --case ascend910 --output results/tap-fresh
python tools/solve_tap_hits.py --hits ../HiTS --binary local/build/hits-hotspot-repro/hotspot.exe --input results/tap-fresh --allow-unqualified-native-diagnostic
```

The solver refuses to overwrite an existing equation artifact. Change `--case`
to `micro150` or `multigpu` for the other input cases; only Ascend has been
solved in this stage. Raw native logs, matrices, references and temperatures
remain local. Compact evidence is in `evidence/tap-thermal-transfer.json`.
Validation: 254 unit tests passed and a fresh documented two-chiplet CLI case
passed (uncalibrated thermal, timing not run). No remote experiment or CI run.
