# Completed stage review and bounded response

On 2026-11-12 Chat mode used connected GitHub to review
`ba4fbebec05745374b20ec0b126f18fcfc9dc1c0..9e0beed449662456d9e2cca453cdfb308cfec341`:
seven consecutive commits and 20 changed files. It reported reading the full
74-commit history and the untruncated 369-entry tree. The completed response is
in [the existing review conversation](https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447).
This receipt summarizes the review; it does not imply review of later changes.

## What was independently checked

The reviewer recomputed the published JSON's 96 path-pair orderings, 85 resolved
interactions, all six independently selected minimum-window comparisons and
the three quoted maximum discrepancies. It found no arithmetic, critical-path
selection or frozen-screen inconsistency and accepted ending the bounded
fabric experiment. It also checked the scoped direct-pin capacity proof, summed
all three integer-flow witnesses, and independently checked geometry witnesses
and candidate counts for all three full source systems.

It did not rerun raw waves, inspect all local logs, execute the regression suite
or independently open the externally hosted DATE paper. The review is code,
history and saved-data scrutiny, not independent physical replication. It
explicitly retained physical benchmark construction and algorithm necessity as
unfulfilled gates.

## Requested corrections and local response

1. **Whole hot-deck equivalence (P1).** The old replay checked X/R/C and model
   hashes but not the entire stimulus/control/include contract. The new
   `validation/xyce_fabric_contract.py` independently reconstructs the allowed
   export from the cold deck and declared hot elements. Only the prescribed
   library/cell references and temperature/RC elements can change, with the
   export's declared element relocation. Supply, PWL, transient settings and
   print controls must remain identical. The model-tree path is derived from
   the output identity, not accepted from an arbitrary hot `.lib` reference.
   Tests reject changed supply, PWL, ambient, time step, include, library,
   process corner, extra directives and missing cell references.
2. **Log-count evidence (P2).** Replay now publishes all 12 cold/hot case
   identities, step sizes, warning counts, unknown counts and log SHA-256s.
   Every retained log has 2785 recognized warnings and zero unknown messages.
   Hashes and counts make the declaration inspectable but still do not supply
   the raw logs to an external reader or certify those known warnings harmless.
3. **Four orientations (source semantics).** The geometry document now explicitly
   identifies four directions as our extension of TAP's width/height-swap
   geometry. Counts include equivalent boxes with different orientation labels.
   Future baselines must share that extension or use the same geometry quotient;
   orientation-sensitive physical ports have not yet been supplied.

The new checker replayed all existing cold/hot waves successfully. The complete
`pairs`, `uniform_controls` and every layout's measured `paths` are exactly equal
to the originally published JSON. Only admission metadata/source hashes and
per-case inventories changed. Original run receipts and raw artifacts remain
unchanged. No new isolated-cell or transistor experiments were launched.

Local validation: 251 tests passed and the documented two-chiplet CLI returned
3 W, 34.1886 C, uncalibrated thermal and timing not run. These post-review changes
are locally verified; the original Chat review does not retroactively approve
their implementation.

## Next complete floorplanning gate

The reviewer proposed beginning with the full sourced Ascend910 six-chiplet
system, freezing a small exactly checkable subdomain before thermal evaluation,
and retaining a larger independent domain under the same rules. Define the
common signal/clock/return, port, layer, wire/spacing, via and keepout contract;
explicit assumptions are permitted but must not masquerade as process data.
Transfer a sourced cooling/material stack rather than the unrelated 3 W fabric
package. Compare geometry-only, aggregate-pin, finite-routing and thermal-plus-
routing decisions in that shared domain. Valid routing requires a witness;
infeasibility needs a certificate or complete exact search; failure/timeout
remains unknown. A new optimizer is conditional on a demonstrated method gap.
