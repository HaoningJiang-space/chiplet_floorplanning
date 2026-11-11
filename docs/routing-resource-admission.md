# E2 routing-resource admission: source audit, not an admitted benchmark

The existing two-net routing contract remains an assumed mechanism control.
No real multilane resource benchmark is admitted in v0.8. Do not interpret
adding eight data nets as evidence of congestion, or a failed heuristic as a
proof that no legal route exists.

## Frozen assembly reference

Inspected IHP Open ADK commit
`093ae2e75fbc0b1eb3838a426cc1a59d37240aa0`. Six reference files are SHA-256 locked
in `tools/sources.lock.json`; the existing bootstrap downloads them to
`local/open-cases/adk-reference/`. Upstream source/model files are not redistributed.
These are read-only admission references; no ADK DRC/LVS execution is claimed.

| Source | What is actually specified | What it does not establish |
| --- | --- | --- |
| [Assembly parameters](https://github.com/IHP-GmbH/IHP-Open-ADK/blob/093ae2e75fbc0b1eb3838a426cc1a59d37240aa0/config/rule_params.json) | Default die edge clearance 200 µm; minimum die area 10,000 µm²; wire-bond-pad clearance 200 µm, with adapter overrides possible | Width of a signal corridor, available routing tracks, or actual die pad order |
| [Cu-pillar adapter](https://github.com/IHP-GmbH/IHP-Open-ADK/blob/093ae2e75fbc0b1eb3838a426cc1a59d37240aa0/pdk_adapters/interconnect/ihp_cupillar.drc) and [interconnect defaults](https://github.com/IHP-GmbH/IHP-Open-ADK/blob/093ae2e75fbc0b1eb3838a426cc1a59d37240aa0/config/interconnect.json) | Option-1 reference: 35 µm attachment opening, 40 µm edge spacing, 75 µm centre pitch | Metal trace width/spacing, signal-layer count or qualified GF180 pad attachment |
| [IntM4TM2 adapter](https://github.com/IHP-GmbH/IHP-Open-ADK/blob/093ae2e75fbc0b1eb3838a426cc1a59d37240aa0/pdk_adapters/interposer/intm4tm2.drc) | Fabrication-layer expressions for pillar/solder attachment and carrier wire-bond pads | A complete routing technology, extracted RC or feasible escape topology |
| [Pad vocabulary](https://github.com/IHP-GmbH/IHP-Open-ADK/blob/093ae2e75fbc0b1eb3838a426cc1a59d37240aa0/config/chiplet_pads.json) | Exchange layers for pad shapes/names and outlines | An implemented PULP die's pad coordinates or signal-to-pad assignment |

In particular, **75 µm bump pitch is not wire pitch**, and **200 µm die spacing
is not the only available routing corridor** when routing below dies is allowed.
Substituting these values into a track-capacity formula would create an
unsupported bottleneck. Nor can the IHP assembly reference qualify attachment
of the currently explored GF180 endpoint without matching its pad/UBM geometry.

## Required next evidence and decision rules

1. Freeze one implemented endpoint's pad/bump geometry, logical net names,
   orientation, signal/return/power assignment and shared-clock group. A locally
   chosen ordering of eight PULP lanes is still synthetic until tied to that
   physical layout. Mapping RTL alone does not supply pad escape or package data.
2. Obtain the corresponding interposer metal/via/keepout rules and declare which
   layers/tracks remain after power, return and reserved resources. Verify that
   the endpoint attachment and carrier technology are compatible.
3. Build capacities from those resources. For a channel containing N parallel
   wires, the necessary geometric packing condition is
   `N*w + (N-1)*s <= W`, with W the usable width after wall/obstacle clearances.
   For a spatial cut, count mandatory cross-cut terminals once per distinct
   signal net; a shared clock is one net, not one clock per data lane. Include
   every allowed layer and bypass, otherwise an alleged upper bound can be too
   small and falsely certify infeasibility.
4. Compare cut demand against a valid capacity upper bound, then attempt actual
   routing and inspect geometry/spacing/escape. Demand above the bound proves
   impossibility only within the stated resource model. Demand below it is
   inconclusive; route-search failure remains `unknown`. Preserve all passing
   low-demand controls, rather than tuning width to force failure.
5. Only geometry/electrical-legal routes advance to group STA using the same PDK,
   clock edges, loads and sourced operating requirement. See
   [timing benchmark admission](timing-benchmark-admission.md). This source audit
   does not add PVT, hot-pad qualification, a timing-critical benchmark or E3's
   constraint penalty result.
