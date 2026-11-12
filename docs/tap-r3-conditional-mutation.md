# R3 conditional legal mutation component

The new `nsga2_legal` policy changes only the NSGA-II mutation candidate
distribution. Population 16, binary tournaments, whole-chip crossover 0.9,
per-chip mutation probability 1/n, rank/crowding elitism and global thermal-key
duplicate suppression retain the original implementation.

For each selected chip in increasing index order, enumerate its existing
individually in-bounds grid/rotation states. Retain those separated from every
other current chip by the declared gap; choose uniformly from this conditional
set. Earlier mutations in the same offspring are visible to later ones. If the
set is empty, leave that chip unchanged. The current state may be selected.
This is conditional sampling, not uniform sampling of full legal layouts.

There is no additional repair stage. Other chips may still overlap after
crossover, so the unchanged full geometry check rejects any remaining illegal
offspring. This minimal intervention isolates conditional mutation before
considering further legalization mechanisms. It does not guarantee a legal
offspring or connected exploration.

All candidate enumeration is charged in `mutation_candidate_checks` and
`mutation_filter_seconds`, included in total elapsed time. Empty sets have a
counter. Each constructed offspring still consumes a proposal under the common
cap; only a new admitted thermal key consumes a thermal query. The existing
initialization, cache, numerical evaluation and objective scales are shared.

Directed tests compare the entire conditional candidate set with independent
full geometry checks on a legal fixture, preserve input placements, and execute
64 distinct synthetic queries with three offspring generations and the same
16 initial layouts. These are algorithm tests, not new thermal experiments.

The completed v4 pilot and its manifest remain historical frozen artifacts.
The current policy source has changed; new R3 runs use the new source-bound
[R3 manifest/runner](tap-r3-protocol.md). Do not pass the old v4 manifest to a
new run or rewrite its hashes. The TAP-derived full policy and concrete cooling
schedule are implemented. Compare this ablation primarily through attained
temperature at common interconnect budgets, and reverse constrained distance;
HV and legality are auxiliary diagnostics, not the physical benefit.
