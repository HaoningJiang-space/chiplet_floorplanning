# Independent sourced geometry domains

This freezes the geometry portion of the next benchmark. It is not yet an
executable thermal/routing benchmark and makes no optimization or physical
qualification claim. The three source systems retain all 6, 8 and 6 chiplets,
their original powers, wire demands and 50 mm interposer. No timing period,
track capacity or power has been changed to manufacture a conflict.

## Domain and evidence

The [DATE 2021 paper](https://people.bu.edu/joshi/files/Ma_TAP-2.5D-DATE2021.pdf),
Table I and Section III-C, specifies a 1 mm centre grid and 0.1 mm minimum gap.
Pinned upstream `system.py:initial_placement` expands each core dimension by
twice its bump-ring width. We adopt a 0.1 mm gap between these expanded
footprints, including their rotation, and require the whole expanded footprint
inside the interposer. This explicitly stated envelope convention must be
shared by all later baselines; it is not a detailed bump escape model.

Every chiplet independently selects its centre and one of 0/90/180/270 degrees.
The four orientations are an explicit extension of TAP's width/height-swap
geometry, not a claim that the upstream model has four direction-sensitive PHY
maps. For geometry alone, 0/180 and 90/270 coincide for rectangles; all four
coincide for squares. Candidate counts include these orientation labels, not
that many distinct geometric boxes. Baselines must use the same extension or
the same explicitly deduplicated geometry quotient until port maps exist.
The domain is the Cartesian product of all individual choices, filtered by
pairwise gap conditions. It is not restricted to common translations, fixed
slots or a common rotation. Square shapes retain four orientations because
future fixed port maps can distinguish them even when their boxes coincide.

`tools/freeze_tap_geometry.py` imports the pinned ledger, derives the source
45 um bump rings, and generates [the domain and geometry witnesses](evidence/tap-geometry-domains.json).
The full Cartesian product is defined, not enumerated. Candidate counts below
include orientations and exclude only individual boundary violations:

| Case | Choices per chiplet, in source ID order | Verified pairs in witness |
|---|---|---:|
| Ascend910 | 2660, 5148, 6708, 6708, 6708, 6708 | 15 |
| Micro150 | 6724 for each of 8 chiplets | 28 |
| MultiGPU | 5476, 3844, 3844, 6068, 6068, 6068 | 15 |

A deterministic area-descending first-fit procedure found one complete geometry
witness for each source case. These are convenient initial placements, not
thermal optima or competitive placement baselines. The checker verifies each
chiplet identity, rotation, grid membership, expanded boundary and pair gap
using exact integer arithmetic in twice-micrometres. It therefore does not
depend on a geometric floating-point acceptance tolerance. Search failure has
the status `search_failed_unknown`, never `infeasible`.

## What remains before benchmark experiments

These geometry witnesses can accompany the separate aggregate-pin flow
witnesses, but neither proves detailed track routing, thermal acceptability,
signal integrity or bandwidth. A common finite-resource package abstraction,
cooling transfer, explicit port assignment and small exact reference domain
must still be frozen before comparing optimizers. No new optimizer is proposed.

Local reproduction:

```powershell
python tools/freeze_tap_geometry.py docs/evidence/tap-source-ledger.json --output results/tap-geometry-domains.json
```

The new tests cover rotation with expanded boundaries, a core-clear/ring-gap
failure, the exact gap threshold, invalid identity/grid and the distinction
between a checked witness and unsuccessful search.

Validation on 2026-11-12: fetch succeeded with local/remote
`main=3974a7f0157e0624826130193b44452c1221225d` before this change. All 248
local tests passed; the documented two-chiplet CLI returned 3 W and 34.1886 C
with thermal calibration absent and timing not run. The three ongoing hot
fabric jobs were not restarted or used to choose this geometry domain.
