# TAP finite-volume admission results

The [frozen contract](tap-fv-contract.md) uses the existing repository package
assembler with HiTS; no new thermal solver or upstream HotSpot patch was made.
The only production schema extension allows per-chip material overrides in a
continuous package/rectangle layer, permitting silicon islands in underfill.
The existing assembly already supports these coefficients and reciprocal faces;
explicit die-sidewall contacts remain restricted to die-island layers.
A new test verifies the harmonic silicon/underfill interface conductance.

## Bounded Gate A outcome

| Source case | Power W | Active nodes | Peak power-layer cell-centre C | Heat balance error W | HiTS/direct max difference K |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ascend910 | 350 | 13600 | 77.1736 | -3.68e-7 | 1.42e-8 |
| Micro150 | 680 | 15920 | 122.5024 | -6.43e-7 | 2.61e-8 |
| MultiGPU | 755 | 14848 | 107.3566 | -1.11e-6 | 3.85e-8 |

These are the previously frozen geometry witnesses, not optimized candidates.
All three matrices are symmetric with negative off-diagonal entries. Doubling
external h changes no internal face coefficient. Original unscaled equation
relative residuals are 1.52e-10 to 3.95e-10. The independent two-solid-column
Fourier reference gives temperature rises [575, 525] K; HiTS differs by
3.41e-13 K. That deliberately artificial analytic control is not hardware.

HiTS uses its unchanged generic CPU GMRES defaults after explicit left diagonal
row equilibration. The unknown remains temperature rise in K; only equation
rows are rescaled. Acceptance additionally checks the original unscaled matrix,
heat balance and a direct solve. No normalized residual is substituted for an
original-equation check. Observed one-run solve times of roughly 0.4–0.5 s do
not establish speedup; mesh, matrix, hardware and timing scope differ from
native HotSpot cases. No CUDA performance claim is made.

Detailed compact evidence and artifact/source hashes:
[evidence/tap-fv-admission.json](evidence/tap-fv-admission.json).
Raw equation arrays and temperature vectors remain local.

## What passing means

The bounded numerical admission needed to proceed with the explicit FV research
model is complete. It is not measured physical calibration, product thermal
qualification, continuum convergence, a proof of model equivalence to TAP's
HotSpot, or completion of the floorplanning benchmark. The original native
Detailed-3D route remains blocked and its counterexample is retained.

In particular, comparing 77.17 C here against the native 118.90 C cannot isolate
the prior boundary defect: package representation, material mapping, perimeter
strips, mesh, and witness positions also differ. Do not use that subtraction
as a correction magnitude or evidence that one peak matches hardware.

## Reproduce

From the local environment, generate into fresh paths, then solve:

```powershell
. ./tools/windows_env.ps1
python tools/prepare_tap_fv.py --case ascend910 --output results/ascend-fv.json
python tools/solve_tap_fv_hits.py --case results/ascend-fv.json --hits ../HiTS --output results/ascend-fv-solve
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/fv-basic-fresh
```

The other source names are `micro150` and `multigpu`. The four added tests check
the analytic half-cell boundary, convection-invariant internal faces, continuous
underfill material interface, and full-source power/core geometry preservation.
All 258 tests and the documented CLI passed locally. No remote experiment/CI.

Next: freeze the exact layout subdomain and finite routing-resource assumptions,
then construct actual routing witnesses and sound impossibility certificates.
Do not expand thermal precision work before a candidate decision actually needs it.
