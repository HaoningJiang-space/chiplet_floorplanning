# Independent geometry domain for the redesigned attachment family

Freeze before the first geometry search. Use the expanded die envelopes from
`tap-ihp-endpoint-contract.md`, independently movable on a 1 mm centre grid with
0/90/180/270 degree rotations, inside the original 50 mm square research carrier.
The carrier size/grid are inherited research choices, not an IHP reticle or
manufacturing-size qualification. Use the pinned ADK default `ASM_b=200 um`
die-to-die spacing; the inspected IntM4TM2 adapter does not override it.

For rectangular dies the existing axis-separation test is conservative for
Euclidean spacing at diagonal corners. State that domain restriction explicitly;
do not describe a rejected close diagonal as proved physically impossible.
Boundary containment and all die pairs are checked in exact twice-um integers.

The endpoint map is authored in the assembly-facing local view, with origin at
the expanded die's lower left. Rotate this map with its die, then translate.
It is not a die GDS coordinate frame; no extra flip-chip mirror is silently
applied. Importing real GDS later requires an explicit frame/mirror conversion.

Search only for initial witnesses with the existing deterministic largest-area
first-fit routine. It uses no thermal/routing score; failure means unknown.
Retain the full independent domain regardless of the witness. No exact thermal
class count, exhaustive feasibility result or optimization quality is claimed.
No pad escape, carrier wiring or PDN qualification is implied by geometric fit.
