# How the original papers use cases and evaluate placement

Read original full texts and the pinned public code on 2026-11-12. This is a
focused experimental-design comparison, not a claim of reproducing their scores.

| Paper | Cases and physical reference | Algorithm comparison and reported measures | Consequence for this project |
| --- | --- | --- | --- |
| [TAP-2.5D, DATE 2021](https://people.bu.edu/joshi/files/Ma_TAP-2.5D-DATE2021.pdf), Sections III–IV | Three heterogeneous examples; conceptual Multi-GPU, CPU/DRAM and Ascend-inspired systems. Public or scaled chip data; default 45 mm carrier, heterogeneous HotSpot stack, constant convection coefficient as sink area changes. | Compare with compact B*-tree/fast-SA initialization; five SA runs, select best; about 4,500 steps/25 hours. Report peak temperature, routing MILP wirelength, thermal maps and TDP tradeoffs. | Our public config uses 50 mm; 64-query shared-first-fit policy adaptation and centre-span objective differ from the paper's routing-aware, long-budget pipeline. R3 is a mechanism comparison, not published TAP reproduction. |
| [ATPlace2.5D, ICCAD 2024](https://yibolin.com/publications/papers/PLACE_ICCAD2024_Wang.pdf), Sections 4.1–4.3, Tables 3/5/6/7 | Ten author-constructed 6–61-die cases with thousands of nets and explicit D2D pin geometry. Compact thermal model trained on five layouts and tested on ten others per case against HotSpot. | Compare adapted TAP and available SP-CP wirelength binary; separate wirelength-driven and thermal-aware modes. Report total wirelength, peak temperature, runtime and selected Pareto curves; include thermal model error and cost. Maximum 80 cores/12 hours; hyperparameter tuning is part of the flow. | Use imported geometry, powers and rotated pin offsets; final legalized layouts need common evaluation. Count training, initialization, tuning and legalization costs. Do not compare our mean centre distance in mm to their total pin wirelength in metres. |
| [DiffChip, ECTC 2025 author preprint](https://arxiv.org/html/2502.16633v1), Sections II/V, Tables III–V | One eight-chip compute/memory system. “Case 1/2/3” are initial, thermal-only and constrained-wirelength scenarios on that system, not three independent chiplet benchmarks. Differentiable conduction model with ANSYS checks. | Distinguish regularized and actual peak temperature/HPWL. Optimize temperature alone, then wirelength under temperature and non-overlap constraints; reevaluate actual layouts with ANSYS. | Keep optimization surrogates separate from the actual reported quantities. A few independent finalist checks can support model relevance without requiring exhaustive physical calibration. This paper's example is not a broad cross-benchmark SOTA comparison. |

The [current public ATPlace repository](https://github.com/PKU-IDEA/ATPlace_pub)
states that its backend changed from HotSpot to ATSim. It also distinguishes
current cooling settings from the paper. Local fetch confirmed the pinned
`fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df` remains origin/main. Treat the paper,
that source revision and our prospective adaptation as separately identified
experimental configurations. Do not substitute their temperatures interchangeably.

Our resulting experimental design is:

1. State the case identity, preserved inputs, placement freedoms, pin mapping,
   package and boundary before selecting algorithms.
2. Check the evaluator on a bounded independent reference and basic physical
   invariants. Do not confuse solving the same equations twice with validating
   the physical model.
3. Separate wirelength-only control, thermal-aware optimization and matched
   constraint comparisons. Report actual temperature and actual selected-layout
   distance together. For current R3, the distance remains explicitly a proxy.
4. Compare mature methods in a shared domain, then isolate the proposed
   component. State adapted policies and changed budgets. Keep query allowance
   and end-to-end time as different cost measures.
5. Extend scale only after one pin-level case is executable. Use the original
   small cases for mechanism evidence and the separate larger cases for scale
   and generalization; do not claim more independent systems from several
   layouts of the same one.

These conclusions concern experimental design. Published speedups, temperatures
and wirelength improvements are not local baseline measurements. Current local
evidence and acceptance states live in [Overall](overall-research-status.md).
