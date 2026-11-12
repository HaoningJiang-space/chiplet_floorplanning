# Online baseline protocol v4

This is a mechanism comparison, not a new optimizer or SOTA result. Use the
three original TAP domains, uniform source powers and frozen FV/HiTS contract.
Direct-coordinate genomes contain independent 1 mm grid centres and four
rotations, checked against complete expanded-footprint geometry. The two-anchor
small-domain graph is not used by the online policies. Routing/timing is not
an objective here; centre span remains a placement communication proxy.

## Common initialization and budgets

Five seeds, 2026111200..2026111204, per workload. Freeze 16 distinct thermal
states for every seed: the known first-fit witness plus 15 objective-independent
sequential constructions, with random chip order and uniform selection among
the next chip's legal candidates. This is biased joint sampling. All methods
evaluate exactly that same list first. Each run has its own initially empty
cache; initialization costs 16 of its 64 HiTS queries. The complete pilot has
45 runs and at most 2,880 charged queries. No cross-run cached values are used.
Initialization uses the listed seed; online policy proposals use seed + 1000000
for every method. This avoids replaying the initialization construction stream.
V1 smoke evidence remains historical; v2 changes only this RNG separation and
extends source fingerprints to the imported key/span/hash helper scripts.
V3 additionally preserves the proposed full four-direction genotype on a cache
hit. Cached objectives come from the first thermal representative, but accepted
SA state must retain the candidate's actual orientation. Saved query rows remain
unchanged. This fixes the state-substitution issue identified by Chat review.
V4 adds the geometry-conformal mesh implementation to source fingerprints;
its search behavior and all initializations/scales are unchanged from v3.

The offline manifest records construction attempts and candidate checks; these
are common setup, excluded from per-run wall time and never claimed as speedup.
Online wall time includes domain option setup, proposals, legality checks,
thermal assembly, HiTS, existing direct reference and boundary checks, and
checkpoint metric computation. A charged thermal query includes all existing
numerical checks; it is not a count of every auxiliary linear solve.

Checkpoints: 16, 32, 64 distinct queries. Cap each run at 10,000 complete-layout
proposals including initialization. An incomplete random construction counts
as a rejected proposal; count its internal candidate checks separately. Cache
hits and invalid proposals cost no new thermal solve but consume proposal/time
budgets. Stop at the cap and report partial results, not infeasibility. A failed
thermal solve consumes an attempt, stops as unknown and is never a high penalty.
No substitution of failed candidates. Fingerprint the implementation, inputs
and clean pinned HiTS source before execution.

## Policies, fixed before comparative outcomes

Random: continue the same sequential legal construction distribution, rejecting
duplicates through the shared evaluator. It is not uniform legal random search.

Multi-weight SA: four chains with thermal weights 0, 1/3, 2/3, 1. Each starts
at its best scalar objective among the common 16, ties by query order. Cycle
chains per proposal, including rejected ones. Each proposal chooses with equal
probability: relocate one chip keeping its direction; change direction; swap
two centres keeping directions; replace one chip's full centre/direction state.
Relocation draws from individually in-bounds candidates; the final complete
layout must pass geometry. Do not repair or restart. A 180-degree change can be
a cache hit. Accept improvement, otherwise exp(-delta/tau); tau decreases from
0.1 to 0.01 geometrically with the fraction of post-initial distinct queries
used. Every chain shares the same run cache and global query budget. The fixed
scales below define the scalar objectives; report absolute tradeoffs as well.

NSGA-II: population 16, rank then crowding binary tournament, elitist selection
from parents plus 16 fresh offspring, nondominated sorting and per-front
normalized crowding. Objective rank uses the existing integer-bin convention.
Random tie breaking uses the run seed. Uniform whole-chip crossover with
probability 0.9, otherwise copy a selected parent. Independently mutate each
chip with probability 1/n by drawing an individually in-bounds centre/direction
state. Reject illegal layouts; no hidden repair heuristic. Suppress previously
evaluated thermal states as offspring, but count proposals/cache hits. The
10,000-proposal cap also bounds offspring generation. A complete 64-query run
has initial population plus three 16-offspring generations. A smoke-only budget
may truncate the final generation and is not part of the comparative pilot.

NSGA-II rank/crowding/elitism follows the original
[Deb et al. algorithm](https://homes.cs.washington.edu/~sagarwal/nsga2j.pdf),
with explicitly discrete operators and duplicate suppression for this domain.
This implementation does not claim reproduction of TAP's B*-tree method.

## Metrics and reuse scope

Per-case scales come from the already-published independent 20-layout diagnostic:
subtract each objective's sample minimum and divide by its sample range. Freeze
these in the manifest, with normalized HV reference (1.2, 1.2). This mathematical
scale is not a physical statement of equal importance. Do not rescale using
algorithm outcomes. Report outside-reference archive points explicitly; points
better than the diagnostic minimum are allowed negative normalized coordinates,
and HV is not a percentage. Compute the 2D dominated rectangle union.

Nondominance uses temperature bins of 1e-6 K and span bins of 1e-9 mm, anchored
at zero. Preserve all actual values and bin members; numerical ties are not
physical-equivalence claims. Publish absolute C and mm, anytime HV, all query
traces, proposals, rejection/cache counts, actual elapsed time and empirical
union fronts. Never label a pooled front globally optimal.

The exact cache key is per-chip centre and orientation modulo 180, valid only
for the fixed centred uniform-core, symmetric-ring, isotropic thermal model
and centre-span objective. It does not imply routing or PHY equivalence.
No global 90-degree rotation reduction or approximate-temperature reuse.

Before the full pilot, validate accounting and selection on controlled examples,
run a local smoke test, publish the SHA, and obtain Chat protocol review. The
separate cache timing and move ablations follow the pilot; no new physics
calibration campaign is a prerequisite.
