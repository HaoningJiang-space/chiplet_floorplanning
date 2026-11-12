# HiTS local native equation integration

2026-11-12: both repositories fetched successfully; floorplanning began at
`3d25fd2`, HiTS at `be59924`. No remote computation was used.

## What is established

A Windows MinGW build of the HotSpot revision pinned by HiTS exports its native
matrix and forcing using HiTS's unchanged observation hook. SuperLU 6.0.1 and
its internal C BLAS provide the native reference. HiTS's default CPU GMRES
solves the same exported equation, with unchanged default acceptance settings.
The upstream EV6 example at 16 x 16 cells per layer has 1,036 unknowns.
The maximum native/HiTS temperature difference was 5.52028e-7 K; the HiTS
original-equation relative residual was 9.93307e-11 and acceptance passed.
The interface check uses a 1e-4 K comparison guard, not a physical uncertainty
bound. Exact revisions, input hashes and measured receipt are in
[evidence/hits-native-windows-smoke.json](evidence/hits-native-windows-smoke.json).

This is an interface smoke check, not a TAP benchmark, physical calibration,
GPU qualification, or speedup measurement. The reported solve time excludes
assembly and setup. No claim that the CPU reference is the accelerated HiTS
backend is made. No materials, source terms or boundary coefficients were
changed to obtain agreement.

## Local reproduction

Use the existing local Windows compiler environment and HiTS checkout. Clone
SuperLU into `local/upstream/superlu` at the revision recorded in the evidence.
Build dependencies (CMake and Ninja are in the local toolchain):

```powershell
. ./tools/windows_env.ps1
cmake -S local/upstream/superlu -B local/build/superlu -G Ninja '-DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc.exe' -DCMAKE_BUILD_TYPE=Release -Denable_internal_blaslib=ON -Denable_fortran=OFF -Denable_examples=OFF -Denable_tests=OFF -Denable_single=OFF -Denable_complex=OFF -Denable_complex16=OFF -DBUILD_SHARED_LIBS=OFF
cmake --build local/build/superlu -j 4
python tools/build_hits_hotspot_windows.py --hits ../HiTS --output local/build/hits-hotspot-repro
python tools/check_hits_native.py --hits ../HiTS --binary local/build/hits-hotspot-repro/hotspot.exe --output results/hits-native-repro
```

Output directories must be fresh. The builder copies upstream sources into
ignored local output, inserts the same three observation hooks as HiTS's
builder, and leaves the checkouts untouched. Source copies retain upstream
licenses. Failed builds retain their command and log. The build is specific to
the tested native API; it does not change production solver selection.

## Next research boundary

Transfer the sourced full TAP Ascend geometry, power, six-layer stack and
cooling into the native assembler, explicitly checking compatibility between
TAP's HotSpot 6 inputs and the pinned HotSpot 7 frontend. Preserve the native
spreader/sink and peripheral package nodes. Freeze candidate and finite-resource
contracts before comparative layout experiments. Do not replace the TAP
350 W package with the unrelated 3 W demo or treat this smoke check as that
transfer. The finite routing-resource benchmark remains incomplete.
