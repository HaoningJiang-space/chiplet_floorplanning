# Native HotSpot package-boundary audit

Follow-up to `787013e`. Remote main was fetched and unchanged before work.
All builds and experiments ran locally. No solver or upstream coefficients were
modified by this audit.

## First-principles requirement and measured violation

For two neighboring solid cells with temperatures at their centers, no contact
resistance and constant material properties, Fourier conduction gives

`R_internal = t_spreader/(2*k_spreader*A) + t_sink/(2*k_sink*A)`.

That internal material resistance must be independent of the external air-side
convection coefficient. For the pinned TAP geometry/materials at a 64 x 64 grid,
this expression is **16.1792 K/W per cell pair**. It is not the whole-package
thermal resistance.

The pinned HotSpot 7 implementation (`9f92256`) first adds
`r_convec * s_sink^2 / A` to the sink layer's `rz` in
`populate_R_model_grid`. The detailed-3D `find_res` then uses half of that `rz`
in the internal spreader/sink connection. The boundary contribution therefore
enters this internal connection as well as the external boundary model.

`tools/probe_hotspot_boundary.py` exports the actual matrix twice, changing only
`r_convec` from 0.009 to 0.018 K/W. It selects one interior spreader/sink pair,
away from the peripheral package links, and reads `-1/A_ij`:

| Quantity | K/W per cell pair |
| --- | ---: |
| Baseline internal edge | 311.0912 |
| Internal edge after doubling external convection resistance | 606.0032 |
| Observed change | 294.9120 |
| Source-formula prediction of extra boundary contribution | 294.9120 |

Prediction error is 5.68e-14 K/W. The invariance requirement fails. This is a
coefficient-level counterexample, not a comparison of peak temperatures and
not a fitting result. It is sufficient to reject this native configuration as
an unqualified physical benchmark. It does not prove every other connection is
correct or quantify how much of the earlier 45.58 K discrepancy it explains.

## Solver separation

A separate unmodified HotSpot 7 build with `SUPERLU=0` was run on the same
Ascend input. Across all eight grid layers its rounded native temperatures
agree with the native direct reference within **0.006452 K**. The print precision
is 0.01 K; the iterative stopping rule also contributes. Its substrate grid
differs from HotSpot 6 by **45.58 K**. Combined with the HiTS same-equation
agreement already reported, this localizes the problem to the native equation
model rather than HiTS convergence. No speed claim is made.

HotSpot 6 remains a historical reproduction reference, not automatically the
physically correct replacement: its heterogeneous lateral neighbor rules also
require care. Do not select whichever version yields the preferred peak.

## Admission and next decision

`solve_tap_hits.py` now rejects default layout admission after exporting the
native equation, retaining the files and an explicit reason. Investigation
requires `--allow-unqualified-native-diagnostic`, and results remain physically
unqualified. The original smoke example and full-case evidence are preserved.
No main thermal solver has been replaced or tuned.

The next bounded task is to choose and document a consistent solid node-location,
interface and package-boundary contract, using independent heat-flux reasoning
and review. Options include a corrected native frontend or a qualified existing
assembler; HiTS can solve either without changing its numerical contract.
Avoid extending this into a general thermal-solver project. Once the required
contract is admitted, return to finite-resource floorplanning comparisons.

## Replay

Use the pinned binary from `hits-local-integration.md` and a generated complete
TAP input directory:

```powershell
python tools/probe_hotspot_boundary.py --hits ../HiTS --binary local/build/hits-hotspot-repro/hotspot.exe --input results/physical-calibration/tap-ascend-native-v3 --output results/boundary-probe-fresh
```

Compact evidence, source identities, and retained artifact hashes are in
`evidence/tap-native-boundary-audit.json`. The experiment changes an external
boundary parameter only to test invariance; it is not a layout benchmark or a
claim that the alternate cooling condition describes hardware.
