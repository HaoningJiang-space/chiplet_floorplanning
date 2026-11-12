# R1 review and disposition before the online pilot

The existing Chat/Thinking session completed GitHub-only review of `366fb290`
and also inspected the subsequent `42d0237` RNG/helper-fingerprint correction.
It read the actual policy/evaluator code, protocol, tests, manifest and saved
smoke summaries. It did not run HiTS or local tests. Its judgment was conditional
acceptance of the experiment design and NSGA-II implementation, with one new
mandatory SA state fix. No new physics calibration or comprehensive smoke
rerun was requested. The next review should follow the 45-run pilot.

## Required corrections, now implemented

1. Cache hits must reuse objectives, not replace the candidate genotype with
   the first cached representative's placement. The evaluator now returns the
   cached values/query index with a copy of the newly proposed placement; saved
   query rows are unchanged. A directed SA regression forces half turns in all
   four chains, confirms the next cycle observes the accepted new directions,
   and verifies 16 initial queries plus eight cache hits with no extra solve.
2. Include `mesh.py` in the source fingerprint, in addition to the key/span/hash
   helpers already added. The final `tap-online-plan-v4.json` binds those inputs.
   All 15 initialization sets and scales are unchanged from v1; operators,
   population, acceptance settings and objective weights were not tuned.
3. Check termination at the complete budget. Controlled tests run all three
   methods to 64 unique queries, including 16 initialization queries; NSGA-II
   completes three offspring generations. A forced cache-only stream reaches
   the proposal cap and preserves its partial result as `stopped_at_limit`.

The reviewer accepted the declared same-domain representation, initialization
accounting, per-run caches, finite proposal cap, unknown-on-solver-failure
semantics, NSGA-II rank/crowding/elitism and the 2D hypervolume union formula.
It warned that GPU illegal offspring costs could hit the proposal cap. Preserve
such partial runs in the pilot; do not discard them or retune the cap afterward.
Keep the fixed HV reference even for outside-reference points, and report
absolute temperature/centre-span values alongside HV.

The already-started targeted v3 SA smoke also completed: 32 HiTS queries,
83 proposals, four cache hits and 47 geometry rejects. All numerical checks
passed. This is execution evidence, not a comparative algorithm result.
V4 only adds mesh fingerprinting to v3; search behavior is unchanged.

After these corrections, 292 current-workspace tests and the documented basic
CLI passed. The final manifest's source hashes and unchanged initialization
sets were checked locally. Three workspace tests belong to pending IHP access
work outside this algorithm milestone. R1 is closed for launching the pilot;
its completion is not proof of method superiority or goal completion.

Review session: https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447
