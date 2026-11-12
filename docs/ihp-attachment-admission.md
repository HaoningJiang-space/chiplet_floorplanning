# IHP source admission and a necessary attachment bound

Research resumed after a successful fetch at `67a1d6a`, with a clean worktree.
The previous Chat review requested compatible endpoint and package sources before
detailed routing. This audit checks one public candidate locally; it does not
replace TAP's process or change any previously frozen routing capacity.

## Compatible source bundle, incomplete public design

The four exact revisions and committed-file hashes are in
[the executable audit evidence](evidence/ihp-tap-attachment-audit.json).
The OpenIntM4TM2, interconnect and ADK revisions exactly match the gitlinks in
[ADK-Tools 6b6ffcf](https://github.com/IHP-GmbH/ADK-Tools/tree/6b6ffcfdfb0deb9f5e0a2259b7193d128c59d2ea).
The routing descriptor digest matches its technology manifest. Source hashes
use Git blob bytes, avoiding Windows newline conversion.

This bundle supplies four routing metals, three via types, layer-specific
width/spacing, a physical stack and named attachment methods. Its descriptor
explicitly distinguishes derived routing pitch and engine-preferred directions
from fabrication rules. It is not the TAP 1 um wire / 2 um pitch mechanism model.
The PDK remains a preview with DRC/LVS work in progress.

The public two-die fixture has two 778 x 2660 um metal-test dies and curated
58-pad lists. It is an integration test fixture, not a powered compute workload.
One die uses the IHP/PacTech `cupillar_opt1`; the other uses `vendorx_microbump`,
explicitly a non-IHP demonstration. Its committed carrier debt contains three
TopMetal2 minimum-spacing/notch markers and 27 recommended pad-exit markers.
Passing assembly checks cannot erase that separate routing debt. The current
ADK-Tools README says user examples and the interposer router are not public
yet; this audit did not obtain them or attempt private access.

## Actual local pad check and negative control

The unchanged pinned `pads_vs_pillars.py` checked both dies against their source
pin lists: 58/58 pads matched on each die, zero findings, **two warnings**.
The warnings concern approximately 5 um auto-resolved shifts and are retained,
not suppressed or presented as exact alignment. The tool's exception is an
upstream policy, not independent proof of contact yield or electrical integrity.

A negative copy displaced the first U1 pillar by 100 um. The same checker
returned exit 1 and a named `MISALIGNED` finding (99.999 um measured deviation).
The original source files were unchanged. These checks concern manifest-level
alignment, not regenerated GDS, carrier DRC, timing, thermal calibration or yield.

## A location-independent capacity obstruction

Question: can existing TAP ring **candidate coordinates** support its incident
conductor counts if a standard IHP/PacTech attachment method is imposed, even
allowing some candidate sites to remain unused?

For option 1, the nominal opening diameter is 35 um and opening edge spacing
is 40 um. Allowing the ADK's 10 nm circle tolerance gives a conservative centre
separation of 74.99 um. Every pair in a 2 x 2 block of the 45 um TAP lattice is
closer: its largest distance is sqrt(2)*45 = 63.64 um. At most one site in such
a block can therefore be populated. This is a spacing constraint, not a change
to graph track capacity.

Partition each of the four existing, disjoint TAP ring strips into k x k blocks,
where sqrt(2)*(k-1)*45 is strictly below the required separation. A strip with
nx x ny candidate sites has the sound upper bound ceil(nx/k)*ceil(ny/k).
Sum the four bounds. Ignoring conflicts between blocks and between strips only
makes the bound more generous. Rigid translations and rotations preserve all
distances, so this necessary test applies before any placement search.

| Attachment method | Nominal minimum centre separation | Block side | Chips failing necessary capacity |
| --- | ---: | ---: | ---: |
| Cu pillar option 1 | 75 um | 2 | 19 / 20 |
| Cu pillar option 2 | 80 um | 2 | 19 / 20 |
| Cu pillar option 3 | 95 um | 2 | 19 / 20 |
| SAC305 solder bump | 130 um | 3 | 20 / 20 |

All three source systems contain a failing chip for every tested method. For
example, Ascend's CPU has 4,092 candidate sites but an option-1 population upper
bound of **1,024**, below its **2,448** incident abstract conductor demand.
The Ascend IO chip passes this necessary test for the three Cu-pillar methods;
that is not a sufficient feasibility certificate.

The result is conditional on the frozen TAP sites and one distinct attachment
per incident conductor. It does not forbid redesigned coordinates/rings,
multiplexed interfaces or a different process. It proves that blindly lifting
the existing graph to these standard attachment methods cannot work, even by
selecting a subset of its sites. It does not prove physical TAP infeasibility or
a positive thermal penalty. VendorX demo rules were excluded from this claim.

## Research consequence and reproduction

Do not route the 77 old representatives against an incompatible endpoint map,
or resize rings after observing thermal outcomes. Next choose either a public
compatible active-die design, or explicitly freeze a redesigned mechanism family
with sourced attachment rules and separately declared power/cooling assumptions.
Retain the TAP results as their original abstraction. A redesigned family needs
a new geometry domain and a new class-cover test; HiTS remains the thermal solver.

```powershell
. ./tools/windows_env.ps1
python tools/audit_ihp_tap_attachment.py --output results/ihp-audit-fresh.json --local-output results/ihp-pad-fresh
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/ihp-basic-fresh
```

The audit requires the four pinned read-only clones under `local/upstream` and
fresh output paths. Three new tests check the bound against exhaustive small
independent sets, strict distance handling and ring/orientation accounting.
No remote computation or new thermal solve is used.
All 270 tests and the documented two-chiplet CLI passed locally (3 W,
34.1886 C reference peak; uncalibrated, timing not run). This source-admission
increment has not yet received a separate Chat audit; the preceding routing
stage's completed review remains scoped to `da65fe9`.
