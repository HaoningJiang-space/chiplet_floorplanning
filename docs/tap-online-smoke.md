# Online baseline implementation smoke, v1

Five real local HiTS runs completed: all three policies on Ascend910, and
NSGA-II on Micro150 and MultiGPU. Every run charged 32 distinct queries,
including the same 16 initialization queries for its workload/seed. All 160
queries passed existing numerical checks. The three NSGA-II runs each completed
one full offspring generation. This validates execution, not method superiority.

| Case / policy | Queries | Proposals | Cache hits | Geometry rejects |
| --- | ---: | ---: | ---: | ---: |
| Ascend / Random | 32 | 56 | 15 | 9 |
| Ascend / SA | 32 | 88 | 4 | 52 |
| Ascend / NSGA-II | 32 | 346 | 21 | 293 |
| Micro150 / NSGA-II | 32 | 196 | 7 | 157 |
| MultiGPU / NSGA-II | 32 | 942 | 71 | 839 |

An independent summary pass checked geometry of every queried layout, unique
thermal keys, equality to the frozen initialization sequence, numerical flags,
plan hashes and the complete event accounting identity. See
[compact evidence](evidence/tap-online-smoke-v1.json). Full event/temperature
receipts remain under `results/physical-calibration/tap-online-smoke-v1`.

The raw counts reveal a setup issue to fix before the main pilot: initialization
and online search currently seed their RNGs identically. Random reconstructs
the initial 15 generated layouts, causing 15 avoidable cache hits. They are
correctly counted and do not leak new thermal queries, but this is not a useful
baseline cost. Use independent deterministic initialization/search RNG streams
before the main pilot; preserve v1 smoke as historical evidence. Do not tune
operators from smoke objective values. Also extend source fingerprints to the
imported key/span/hash helpers before freezing the final main-pilot manifest.

All 291 current-workspace tests and the documented two-chiplet CLI passed.
Six new tests cover initialization/query accounting, cache/geometry separation,
query caps, failure-as-unknown, HV rectangle union and NSGA-II rank/crowding/
elitist selection. Three workspace tests cover uncommitted IHP access work
outside this milestone. The code/protocol was published as `71b6553`; the
main 45-run pilot has not started. Chat protocol review is the next step.

## V2 setup correction and regression

Online policies now use seed + 1000000, while manifest construction retains
the original seed. Key/span/hash helpers are included in the implementation
fingerprints. All 15 per-case/seed initialization sets and objective scales
were compared and are identical between the v1 and v2 manifests. Operators,
acceptance, population, objective weights and query budgets were not retuned.

A further real Ascend Random run at budget 32 completed with 34 proposals,
zero cache hits and two rejected constructions, eliminating the systematic
initialization replay. See [v2 regression evidence](evidence/tap-online-smoke-v2.json).
All policies passed controlled accounting/selection tests with the new stream;
the complete 291-test suite and basic CLI passed again. V1 smoke remains an
execution check of the unchanged operators, not comparative v2 trial data.
The five-seed full pilot must use `tap-online-plan-v2.json`.
