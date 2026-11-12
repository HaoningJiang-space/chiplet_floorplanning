# Local attachment access cell v1

Freeze before geometry checks. Keep the published 75 um endpoint lattice and
all source conductor identities. Reuse OpenIntM4TM2 `a700e4a`'s unchanged
CuPillarPad-based generator with interconnect PDK `6a519e9`, option 1. Draw actual
35 um opening and 50 um TopMetal2 enclosure geometry from that generator, not a
replacement square Pad. Preserve recognition layers and the attachment bodies.

For each signal at its centre, add one TopVia2 cut (0.90 um square), enclosed by
the generated TopMetal2 and a 1.90 um wide TopMetal1 east-going stub. Add one
TopVia1 cut (0.42 um square) at the same centre, enclosed by that TopMetal1 and
a 0.62 um wide Metal5 north-going stub. The dimensions follow the pinned
descriptor: TV2 enclosure 0.50 um each side; TV1 enclosure 0.42 um on TM1 and
0.10 um on M5. Stubs end at the east/north boundary of the 75 um square cell.
Their opposite ends extend half their widths beyond the pad centre. Via arrays,
current capacity and electrical parasitics are not inferred from one cut.

These two stubs belong to the SAME conductor and provide two optional access
ports, not two independent capacity slots. Each terminal uses one pad; future
routing must preserve its identity and count shared resources globally. Stubs
stay aligned with global package axes even when the chip rotates; only pad
locations/identities transform. Preferred metal direction is an engine choice,
not a fabrication restriction.

All checks in this stage concern a local access cell and its nearest neighbours:
actual opening enclosure, trace width, cut size, cut enclosure, same-layer
spacing and connected overlap from pad to both access ports. Check the full
3 x 3 all-signal tile, a stronger case than checkerboard population. Translated
copies farther away cannot introduce a closer pair because each unit stays in
its 75 um cell. Instantiate the same units at every signal endpoint of all three
published placement witnesses; reserved PDN sites carry only the upstream pad
cell, while unpopulated sites are absent. No metal routing through another Pad
and no chip-level relay is granted by this construction.

Use local KLayout geometry operations and reread exported GDS. This is a
specified subset of geometric checks, not the complete Ruby fabrication deck,
LVS, density/fill, edge-seal finishing, electrical SI/PI, thermal calibration or
manufacturing signoff. In particular, PDN pads remain unconnected and global
routes remain absent. Signal-via placement under this Pad is an explicit design
choice pending full process/assembly qualification; no undocumented exclusion
is invented or silently certified. The frozen design is not adjusted to obtain
a pass: any failure is recorded and leads to a separately identified revision.
