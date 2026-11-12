# R2 closed: algorithm work authorized to proceed

The existing Chat/Thinking review completed at published main
`d86fec3b2d30d215ec48ce06f1ce90a708380b84`, through GitHub only.
Review session: https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447

The reviewer reported reading the 13 commits after its R1 reference, complete
pilot/analysis JSON, verifier/reporter, both figures, TAP proposal adapter,
ATPlace importer and AGENTS. It independently recomputed geometry, centre span,
thermal keys and checkpoint/final hypervolume from the 2,880 published layouts;
it found no discrepancies. It confirmed paired wins and differences, including
the negative MultiGPU SA paired median. It did not run HiTS or obtain the local
raw event logs; policy replay remains local execution evidence.

R2 accepts the pilot. No additional seeds, repeated audit or physical precision
campaign is needed. NSGA-II is promising but not a stable universal winner.
Its median illegal-proposal fractions (Ascend/Micro/GPU: 86.3/80.7/88.1%) motivate
a specific question: does legality-aware generation improve Pareto quality at
the same thermal query budget, or merely reduce proposal overhead?

## Accepted next stage: R3

- Reuse existing Random, multi-weight SA and NSGA-II results under unchanged
  v4 domains, evaluator, initialization and accounting.
- Add complete TAP-derived coordinate SA: close/jump proposals, original-style
  dynamic normalization/acceptance, and a declared finite-budget cooling schedule.
  B*-tree is the upstream initializer, not its main thermal search representation.
- Add legality-aware NSGA-II while retaining population, selection, crossover
  and elitism. Freeze the conditional legal mutation/finite repair policy before
  comparative runs; charge geometry checks and every repair attempt.
- Develop with one seed. Main comparison uses the first three v4 seeds
  (2026111200..2026111202), 64 queries including the same 16 initial layouts.
  Two new methods x three workloads x three seeds = 18 runs, at most 1,152
  new thermal queries. Do not select seeds based on their previous outcomes.
- Report paired HV against original NSGA-II and published-policy baseline,
  absolute temperature/span, query curves, illegal rate, diversity, cache,
  proposal effort and elapsed time. Improved legality without quality gain is
  an acceptable negative result. No significance or SOTA claim from three seeds.

In parallel, connect imported ATPlace Case1/6/10 (6/20/61 chiplets) to a declared
common evaluator using source carrier sizes, power and rotated pin-to-pin
Manhattan distance. Begin with one-seed execution checks, then NSGA-II and its
legality variant at 32 queries/one seed: at most 192 comparative queries.
Package/grid assumptions must be explicit; record actual memory/mesh limits if
61 dies cannot execute. Native ATPlace initialization/legalization remains a
separate integration path; a thermal-aware shared-model gradient adaptation
still needs a compatible differentiable model and charged training cost.

Next review follows the completed R3 comparison, not every small commit.
Implementation and the concrete schedules/operators must now be frozen in an
R3 protocol before new comparative thermal runs. The active research goal is
not complete: published baselines, method ablations and scale extension remain.
