# Archived bounded local Pad access check

This closes the previously started IHP access job. No new geometry experiment
or physical calibration campaign was launched during this archival step.
It is separate from the original TAP geometry used by the ongoing online
algorithm pilot; the new IHP footprints are not substituted into that evaluator.

The source-generated CuPillarPad geometry is connected to the declared TM1/M5
access stubs under the [frozen contract](tap-ihp-local-access-contract.md).
Saved GDS was reread and its instance locations/types matched the endpoint map.
All three completed placement witnesses passed the specified width, spacing,
cut shape/count, enclosure, component and grid checks:

| Case | Signal endpoints | Populated Pads / matched GDS instances |
| --- | ---: | ---: |
| Ascend910 | 4,896 | 10,232 |
| Micro150 | 20,480 | 42,864 |
| MultiGPU | 13,824 | 29,184 |

The nine-signal nearest-neighbour tile passed the same subset. Moving each
TopVia1 cut by 1 um caused nine outside-Metal5 violations, correctly rejecting
the negative control. The three checker regression tests also reject a narrow
trace, missing cut and an unrelated off-grid polygon.

## Earlier failure and correction

The initial checker reported 4,320 off-grid vertices in the source's circular
Pad/opening approximations. The pinned upstream
[off-grid deck](https://github.com/IHP-GmbH/OpenIntM4TM2/blob/a700e4a04724e0e2f266b3161eb19e0476b747d3/libs.tech/klayout/tech/drc/rule_decks/3_1_offgrid.drc)
explicitly exempts circular drawn shapes. The corrected local checker exempts
only exact translated source-circle templates, not an entire layer. The native
Pad geometry was retained; the earlier failure is preserved in the archived
summary. This subset checker is not an implementation of the entire upstream
raw/merged off-grid rule or fabrication deck.

The Windows runtime uses a local archive of OpenIntM4TM2 `a700e4a` and two Tcl
argument-quoting changes, with before/after hashes. They correct Windows path
handling without changing geometry. The interconnect PDK is `6a519e9` and the
local KLayout version is 0.30.13. The original source repositories remain clean
at those pinned commits; the patched runtime is separate.

## Evidence boundary and archive

[Published summary](evidence/tap-ihp-local-access.json) contains all findings,
the negative control, runtime patch receipt, input/artifact hashes and the
earlier checker failure. At archival time, every saved GDS and access-map digest
was rechecked and all map lengths matched signal counts. The original receipt
did not include a checker-code fingerprint; the archive records the present
checker snapshot hash and does not mislabel it as an original execution hash.
The full GDS and maps remain local in
`results/physical-calibration/tap-ihp-access-v2`.

Acceptance is based on the explicit result statuses and findings, not the
generator's process exit code alone. This establishes a bounded local access
witness, NOT whole-chip detailed routing, supply/return connectivity, via current
capacity, SI/PI, LVS, fill/density, process qualification or manufacturing signoff.
PDN Pads are reserved but unconnected; global routes are absent. Two access
stubs belong to the same conductor and cannot be counted as two independent
capacity slots. No new thermal or timing calibration claim follows.

The `layout` optional dependency pins KLayout for reproduction. The checker and
runtime preparation scripts are now preserved with their tests; algorithm work
continues independently on its frozen v4 inputs.
