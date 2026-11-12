# Finite aggregate routing: thermal-class cover gives zero penalty

Remote was fetched at start: `main=0d4521f`, clean and current. The
[resource contract](tap-global-routing-contract.md) was written before the
routing experiments. Everything ran locally; no resource, clock or demand
was adjusted in response to a failed layout.

## Concrete finite resources and witnesses

Unlike the complete direct pin-clump abstraction, this graph has finite shared
track, via-site and distributed bump-bin access capacities. Integer bump centres
are generated in all four nonoverlapping source ring strips and rotated with
the chip. The router forbids using another chip as a relay. Shared usage counts
both directions and all commodities against the same resource.

The three original geometry witnesses all succeeded:

| Case | Directed wire units delivered | Graph nodes | Shared resources | Max core-edge utilization |
| --- | ---: | ---: | ---: | ---: |
| Ascend910 | 2448 | 5298 | 8276 | 0.996 |
| Micro150 | 10240 | 5296 | 8264 | 1.000 |
| MultiGPU | 6912 | 5366 | 8480 | 1.000 |

Utilization is for the fixed sequential search's particular flows, not minimum
congestion or proof of an unavoidable bottleneck. Each complete flow was verified
for allowed directions, exact commodity conservation, delivered demand, pin
access and global shared capacities independently of max-flow solver state.
Tests reject omitted/duplicated demands, modified flow, illegal edges and
shared overcapacity; search failure is explicitly unknown. Fractional demands
are rejected rather than truncated in the verifier.

## Existential cover of all thermal states

The frozen exact domain contains 4,928 legal layouts and 77 thermal equivalence
classes. Regrouping decoded legal ordinals reproduced those 77 classes. In
fixed ordinal order, the first state tried in every class had a valid integer
routing witness: **77/77 classes covered in 77 attempts**. Each compressed
artifact was re-read, its geometry revalidated, its thermal class checked, its
graph rebuilt and its flows independently replayed. No failed attempt was
hidden and no new thermal solves were needed.

Let G be the frozen geometry set, F its routable subset in this aggregate graph,
and T any objective constant within each proved thermal class. For every x in G,
the cover supplies y in F in the same class, so T(y)=T(x). Since F is a subset
of G, min_F T >= min_G T. Taking a covered representative of a minimizing class
gives the reverse inequality. Hence **min_F T = min_G T**, or delta_T_graph=0.
This is an exact conditional cover proof, not a small numerical temperature
difference. It does not identify which class is hottest or coldest, prove every
layout routable, or give the absolute optimum temperature. It remains valid
without evaluating the redundant thermal fields, under the frozen equivalence
assumptions. For actual later evaluation use each class's canonical thermal
representative rather than accumulating floating-coordinate differences.
The thermal generator now enforces this by mapping rotations modulo 180 degrees
for the declared centred uniform-core model only. All 462 individual chip
half-turn checks over the 77 representatives produced exactly equal input
dictionaries. Routing retains the original orientation and bump coordinates.
The three previously admitted numerical case inputs remain exactly unchanged;
see [canonical-input evidence](evidence/tap-thermal-canonical-inputs.json).

This is a useful structural result and a negative algorithm-motivation result
for the current abstraction. It does not support developing a new optimizer
for a positive routing-induced thermal penalty here.

## Physical limitation stays explicit

The two signal layers, ideal reference planes, via landing rule, switchbox
counts and access to either layer are shared explicit assumptions. Pin identity,
clock/return allocation, detailed escape, track identity/spacing inside each
bin, and channel timing/SI are not qualified. Aggregate feasibility is a
relaxation of those detailed constraints, not a manufactured routing result.
This is not a certified relaxation of any particular real manufacturing stack:
the assumed layer count can also exclude routes that a real multilayer process
allows. A mapping to a compatible detailed model is still required.
Accordingly, delta_T_graph=0 is not delta_T_physical=0, and does not complete the
original sourced physical benchmark goal. The next meaningful step is to check
whether a sourced detailed access/track model preserves these witnesses, not
reduce their capacities until a conflict appears.

## Reproduce and audit

```powershell
. ./tools/windows_env.ps1
python tools/tap_global_routing.py --case ascend910 --output results/ascend-global-fresh.json
python tools/check_tap_routing_cover.py --output results/tap-cover-fresh
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/tap-route-basic-fresh
```

Fresh destinations are required. Failed attempts and successful compressed flows
are retained locally. Published [compact evidence](evidence/tap-global-routing-cover.json)
contains protocol/input/source hashes, all 77 class statuses, witness artifact
hashes and independent replay summaries. It contains no raw local process logs.
All 267 unit tests and the fresh documented two-chiplet CLI passed locally.
The [completed GitHub-only Chat review](tap-routing-chat-review.md) records
independently checked scope, remaining certificate limits and the next physical
access experiment.
