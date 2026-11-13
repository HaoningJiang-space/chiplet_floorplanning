# Case1: one-seed pin-guided candidate-screening ablation

This follows the completed [Case1 Chat review](atplace-case1-review.md). It is
an exploratory mechanism comparison on one public input, not a SOTA benchmark
or stable-superiority claim. Keep the accepted Case1 source geometry, powers,
pins, common FV recipe and existing numerical admission. Do not change R3.

## Frozen domain and budget

- ATPlace Case1 at `fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df`, 42x42 mm,
  6 dies, 780 W, 3,168 two-pin nets, no added external bump ring.
- Integer 1 mm centre grid, 1 mm separation, all four quarter-turn orientations.
  Pin distance is the unweighted SUM over source nets, in m, not mean centre span.
- One seed `2026111200`; the online RNG uses seed+1,000,000. No outcome-based
  seed replacement. Each method uses its own initially empty thermal cache.
- Sixteen shared initial layouts, including the accepted base. The other 15
  are generated without temperature or distance selection: descending-die-area
  sequential construction with seeded random ties, uniform among the next die's conditional legal
  states. Require 16 distinct thermal keys and save the exact ordered list.
  This construction is not uniform over joint legal layouts.
- Each method pays for 16 initial solves plus at most 32 fresh online solves:
  48 total per method, at most 96 for the comparison.
- Per-method hard limits: 512 proposals including initialization/retries,
  2,048 complete pin-objective computations, 2,000,000 candidate geometry checks.
  The shared offline initialization's checks are charged to both methods;
  unretained construction attempts reserve proposal IDs before the 16 actual
  initialization submissions. Construction time is separately reported as shared
  offline work, not silently included in measured online wall time.

The first objective-free initializer used random die order and exhausted the
same 2,000,000 candidate checks before creating a manifest or running any thermal
solve. [Preflight receipt](evidence/atplace-case1-initialization-preflight.json).
Before formal freezing, only the construction order was changed to largest
first, with the same seed and caps. No algorithm quality result was observed,
discarded or used to select the initialization procedure.

## Two methods, one change

Both use NSGA-II population 16, rank/crowding binary tournament, whole-die
uniform crossover with probability 0.9, per-die mutation probability 1/6, and
elitist selection of 16 from parent+16 offspring. Ranking bins are 1e-6 K and
1e-9 m to handle numerical ties; final constrained metrics use raw values.
Tournament ties and survivor tie keys use the seeded RNG. Partial final
generations remain in the evaluation archive even if survivor selection has
not occurred. The different RNG draws required by screening are part of the
declared policies; a paired seed is not a promise of identical trajectories.

A (`nsga2_legal`) uniformly chooses one placement state for the mutated die,
conditioned on separation from all currently fixed other dies.

B (`nsga2_pin_guided`) draws up to four different states from exactly the same
conditional set. For each resulting complete legal layout, compute full pin
length. Uniformly choose among those with L<=L0. If none qualifies, choose a
minimum-L candidate with seeded uniform tie breaking. L>L0 remains legal;
the metric threshold is a search preference, not a new physical feasibility rule.

After crossover, two other fixed dies can still overlap. A one-die mutation
cannot repair that pair, so B uses A's uniform choice in this context without
computing a misleading pin score on an illegal layout. Later mutations may
repair it; the final full geometry check remains mandatory. Empty conditional
sets leave that die unchanged. Report both events. Each enumerated option costs
one candidate check; checking pairwise separations within that option is not
misreported as several separate candidate evaluations.

Every B pre-screen pin computation is charged, including discarded candidates.
The selected complete layout's objective is recomputed by the accepted evaluator
and charged again. Duplicate full-state submissions consume a proposal and
remain in the event log, but skip redundant objective/thermal work. A new full
orientation with a previously seen thermal key is retained as a new evaluation
row and can become offspring, influence ranking and win final selection.
Prescreened candidates without a thermal evaluation are never joint witnesses.

The frozen source/input hashes, HiTS revision, initial list, constraints and
costs are bound by the manifest. Source/model changes after freezing require a
new explicitly identified protocol, never silent adaptation to observed results.

## Metrics and termination

Use the prior accepted base as the only primary constraint anchor:
L0=73.840208806 m and T0=107.45047721858577 C. Require exact reproduction of
base's stored T and L before search; a mismatch is failed/unknown, not a reason
to relax thresholds. These are research anchors, not fabricated product limits.

Report minimum T at raw L<=L0, and minimum L at raw T<=T0. Ties select the other
objective then evaluation-row index. Keep selected full placement, both raw
objectives, solve ID and cache provenance together. Missing attainment stays
null. B's improvement is A minus B (K, m and percentage). Pareto membership
is auxiliary, computed from actual raw joint points; no interpolation.

Checkpoints at 16/32/48 consumed thermal solves include all evaluated complete
states before the next fresh solve, including new cached orientations at the
same query count. Stop immediately at 48 fresh solves, even mid-generation.
If proposal, pin or candidate checks reach their limits first, retain results
as `capped`; do not extend budgets. Numerical, source, solver or anchor failure
is `failed_unknown`, never a high-temperature penalty or global infeasibility.

Save all full rows, events, thermal receipts, raw Pareto states, selected joint
witnesses, caps and cost counters. Report pin pre-screen time, total solve time,
total elapsed time and shared initialization time separately; wall times are
observations on this workstation, not a claimed controlled speedup. Verification
recomputes geometry/pin values and replays the policy against saved thermal
responses (including exact submitted physical-input hashes), without new solves.

## Local entry points

```powershell
. ./tools/windows_env.ps1
python tools/run_atplace_search.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-search-plan-v1.json --freeze
python tools/run_atplace_search.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-search-plan-v1.json --method nsga2_legal --hits ../HiTS --output results/atplace-case1-search-v1/nsga2_legal
python tools/run_atplace_search.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-search-plan-v1.json --method nsga2_pin_guided --hits ../HiTS --output results/atplace-case1-search-v1/nsga2_pin_guided
python tools/run_atplace_search.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-search-plan-v1.json --report results/atplace-case1-search-v1/nsga2_legal/result.json results/atplace-case1-search-v1/nsga2_pin_guided/result.json --output docs/evidence/atplace-case1-search-v1.json
```

Use an already frozen plan directly; the exclusive-write commands will not
overwrite history. Commit/push the implementation and manifest before running,
then verify, summarize and push the full local result, including negative or
capped outcomes. No additional seeds, cases or physics-fitting campaign here.
