# Chat review: physical-metric migration accepted

The existing Chat/Thinking session completed its GitHub-only review of
`12a7f2a1804358747e6e12cc35b4fc5a892bb321`, covering the four commits since
its R2 reference `d86fec3`. Session:
https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447

The reviewer reported reading the complete original pilot, R3 manifest,
physical report, development smoke and named algorithm/reporting sources.
It independently recomputed all 18 physical anchors, the 270 final constrained
layout selections from 45 runs, all checkpoint selections, and paired statistics
at all three anchors. It found no mismatches. It also compared the copied
initializations and recomputed constrained selections from the 64 development
smoke layouts. It did not independently execute the local test suite, HiTS or
policy replay; those remain local execution evidence.

Decision: the main metric and pairing are correct, and no new blocking code or
fairness defect was identified. Proceed with the frozen 18-run R3 comparison;
do not add another algorithm, more seeds or another physics-precision campaign.
Judge conditional mutation by constrained physical quality, with legality and
runtime used to explain its behavior. Accept a negative quality result if it
only improves the legal-proposal fraction.

One concrete report addition was requested: `report_tap_physical.py` omitted
`mutation_candidate_checks` and `mutation_filter_seconds` from its compact
effort view even though raw results already saved both. Both are now carried
into the report, alongside construction checks and empty mutation-set counts.
An existing reporting test checks that the extra costs survive aggregation.
This changes neither search nor thermal results. A new source-bound manifest
`tap-online-plan-r3-v2.json` preserves the old R3 manifest and smoke provenance.

Two interpretation limits remain: the TAP-derived single chain starts at the
shared first-fit and uses a query-budget cooling adaptation, so a weak result
does not establish that the original TAP pipeline is weak; its source adpTWv2
zero thermal weight below 80 C is retained rather than tuned for Ascend.
The next requested review is after the formal R3 comparison, not another
foundation or thermal-calibration review.
