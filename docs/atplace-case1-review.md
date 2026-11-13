# Case1 Chat review: accepted within the declared model

On 2026-11-12, fetch succeeded for the main project, HiTS and ATPlace; all
remained at their recorded revisions. Chat/Thinking (Extra High) reviewed
`b72da5201a37e0c530865e25def3a4da3ce30ff4` through the connected GitHub account.
[Review conversation](https://chatgpt.com/c/6af66afe-ced4-83e8-883b-dac7a131b98f).
The old conversation had reached its length limit. The new page temporarily
had loading/connection errors; after the user restored the connection, the
complete answer and both method/budget tables were retrieved. No new account
permissions, upload or remote experiment was used.

The reviewer independently parsed the pinned upstream `.blocks`, `.power` and
`.nets`, then recomputed all 3,168 net lengths for each of the three layouts
without calling our `pin_objective`. Source counts, dimensions, 780 W total,
carrier/gap legality, all three total lengths and rotation conventions matched.
All seven listed executed-source hashes matched the reviewed Git commit. Chat
did not independently run HiTS or the local test suite.

Verdict: no correctness blocker was found for the declared Case1 geometry,
uniform-die model and three-layout evidence. Two limits remain explicit:

- Bounds-based thermal equivalence requires fixed uniform isotropic materials,
  uniform power and fixed boundaries. It does not apply unchanged to nonuniform
  blocks, anisotropy or temperature-dependent power.
- Base and moved layouts use 70x68 and 71x69 geometry-conformal meshes. Their
  1.187659 K difference is a prediction of the common discrete FV evaluator;
  conservation alone does not establish mesh-independent real-package accuracy.

Approved next scope: Case1 only, one seed `2026111200`, two NSGA-II methods with
the same legal domain, population 16 and R3 crossover/mutation probabilities.
A uniformly chooses conditional legal mutation states. B samples up to four
legal states and prefers one satisfying the frozen pin budget; otherwise it
chooses minimum pin distance, with seeded tie breaking. This is a screening
ablation, not a new optimizer or SOTA claim. The complete procedure must be
frozen before runs, including treatment of still-illegal crossover intermediates.

Recommended common limits per method: 16 shared initial layouts (including
base), private empty thermal caches, 32 additional fresh thermal queries,
512 full-layout proposals including initialization, 2,048 complete pin metric
calls and 2,000,000 conditional candidate checks. Keep capped/failed results;
never replenish a run because its result is weak.

Freeze L0=73.840208806 m and T0=107.45047721858577 C from the already accepted
base. Report minimum attained T at L<=L0, and minimum L at T<=T0, using actual
joint witnesses. Preserve full-state rows for new orientations even on thermal
cache hits, with their own pin lengths, ranking identity and thermal solve ID.
The old R3 thermal-key row suppression and centre-span metrics cannot simply
be reused. Record 16/32/48 thermal checkpoints, Pareto states, all costs and
attainment; one seed supports a mechanism diagnostic, not stable superiority.

Next checkpoints are the frozen implementation/protocol and the completed local
comparison. Do not add thermal precision campaigns, larger cases, STA or seeds.
