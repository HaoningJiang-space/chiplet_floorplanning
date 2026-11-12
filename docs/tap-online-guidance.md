# Completed Chat guidance for the online baseline stage

The existing Chat/Thinking session completed a GitHub-only review at
`3a7fccb77ddbf8e6c706326e25a116b0037b621a`, covering four commits after
`018a1bd`. It reported reading the sensitivity and structure implementations
and complete published JSON, checking ranges, source-contribution arithmetic,
component counts, 1,155 traces/summaries and the eight Pareto bins. It found no
hard error requiring rejection of the conclusions. It did not execute HiTS or
the local regression suite. The old 360-trace compatibility remains supported
by locally executed tests, not an independently executed reviewer test.

The review explicitly retains the biased-construction sampling limitation and
the lack of significance evidence from one RNG seed per starting class.

## Accepted research direction

Use the same direct-coordinate representation, full geometric legality checker,
thermal evaluator and cache policy for random construction, multi-weight SA and
NSGA-II. These are mechanism baselines, not a SOTA claim. Native B*-tree packing
has a different reachable layout set and should later be a separate
representation/legalization experiment. Do not implement it merely to label
the current comparison a strong same-domain baseline.

The reviewer recommends a bounded first pilot:

- Three existing workloads, five fixed seeds each, three methods.
- The same 16 distinct legal thermal states initialize all methods for a seed:
  first-fit plus 15 objective-independent sequentially constructed layouts.
- A budget of 64 distinct thermal evaluations INCLUDES the initial 16. Report
  checkpoints at 16, 32 and 64; total planned charged queries are 2,880.
- SA uses four chains with fixed thermal weights 0, 1/3, 2/3 and 1, a shared
  per-run cache, and predeclared move/rotate/swap/joint proposal probabilities.
- NSGA-II uses population 16. Duplicate offspring and illegal proposals do not
  become free unlimited computation: cap attempts, record stagnation, and state
  precisely how new-query budgets and generation completion interact.
- Freeze objective normalization and hypervolume reference points from the
  independent diagnostic before comparative results. Also report temperatures
  in C and centre-span proxies in mm, including points outside an HV reference.
- Log thermal queries, cache hits, proposals, illegal proposals and total wall
  time separately. Keep run caches isolated so repeated initialization is not
  free for later methods. An empirical union front is not a global optimum.
- Keep cache timing ablation separate, with the same proposal stream on/off.

These are accepted design recommendations, NOT an implemented or frozen online
protocol yet. The next milestone must supply concrete operators, SA acceptance
and scheduling, NSGA-II selection/crossover/mutation, initialization manifests,
budget/failure checks and metric tests. Have Chat inspect that code/protocol
before the main pilot, then review the three-workload pilot results.

No new SPICE, manufacturing signoff or thermal precision expansion is required
to proceed. The numerical physical invariants and scope labels remain in force.

Review session: https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447
