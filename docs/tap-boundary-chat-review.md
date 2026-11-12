# Completed Chat review of native thermal transfer

Review completed 2026-11-12 in the existing ChatGPT Chat/Thinking session,
visible thinking strength 极高:
https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447

Reviewed HEAD: `935990530af1f981b7fa7e09654a7c43bd423c0b`.
Reviewer reported direct GitHub inspection of the four commits from `9e0beed`,
19 changed files, 78 history entries, and an untruncated 384-entry tree. Only
connected GitHub was used; no new Chrome authorization, upload, or remote test.
The complete reply was read after the UI reported completion.

## Accepted findings

- Whole-deck replay repair and its negative tests close the prior review gap;
  bounded three-layout Fabric exit remains complete.
- Three complete TAP six-layer input transfers are supported by saved evidence;
  only Ascend was thermally solved. Input acceptance is not physical acceptance.
- Direct inspection of pinned HotSpot 7 `9f92256` confirmed the convection term
  propagates from sink `rz` through `find_res` into the internal spreader/sink
  edge, while a separate sink-to-environment branch remains present. This is
  not explained by boundary-node elimination.
- The reviewer independently checked the 16.1792 + 294.912 = 311.0912 K/W
  calculation and the doubled-convection counterexample. Rejecting this native
  detailed-3D configuration for layout admission is appropriate.
- HiTS/native numerical agreement concerns the same supplied equation only.
  The full cause of the 45.58 K HotSpot 6/7 discrepancy remains unproved.
  HotSpot 6 is not automatically a physically correct replacement.

## Limits and open items

The reviewer directly read the fixed HotSpot 6/7 sources but could not locate
and directly inspect `HiTS@be59924` through its GitHub connector. The HiTS
revision and numerical results were checked as published provenance/evidence,
not independently reproduced. Raw local matrices, waves and logs were not
rerun. The reported 254 tests and CLI are author-local evidence; the reviewer
reported zero GitHub Actions runs at the reviewed HEAD.

One interior edge counterexample suffices for rejection, not for certifying all
other edges. Thermal border compatibility remains a source-representation
restriction, not a physical keepout. Generated files alone never imply admission.
A future assembler repair must add an actual native boundary-invariance
regression; that repair and regression are not yet complete.

## Bounded next-stage contract adopted

A. Select one explicit node-location/interface/package-boundary equation
contract. Prefer an existing suitable finite-volume assembler or a limited
local native correction separating material and convection resistances.
Validate with one two-solid-layer analytic example, one external-convection
internal-edge invariance check, and the full Ascend 350 W conservation/numerical
case. Sink-to-ambient distance must match the selected node convention. Do not
require different discretizations to converge to identical temperatures.

B. Freeze a small exact-checkable full-six-chip layout subdomain and the larger
independent domain. Freeze ports, signal/clock/return allocation, layers,
width/spacing, via and bypass resources, and keepouts. Unsourced choices must
be explicit common assumptions, not real-package qualification. Distinguish
geometry-legal, routing witness, certified impossible, and search unknown.

C. On that fixed domain and common evaluator, determine whether finite routing
resources change the thermal optimum. A routing witness for a global finite-domain
thermal optimum proves zero resource penalty. A warmer feasible result alone
only bounds the penalty; positive penalty requires excluding all colder
candidates. No new optimizer is justified until this mechanism/method gap exists.

This receipt records review of `9359905`; its own documentation-only commit is
not claimed to have been reviewed. The overall floorplanning goal remains active.
