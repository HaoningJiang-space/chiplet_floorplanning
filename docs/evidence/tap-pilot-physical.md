# Layout quality at shared physical constraints

Retrospective reanalysis of the completed 45-run pilot: these physical anchors were chosen after that pilot. No new thermal solves or new seeds; original evidence remains unchanged.

Primary: minimum attained peak temperature under a common demand-weighted mean centre-span budget. Reverse comparison: minimum attained centre span under a common peak-temperature ceiling. These are centre-distance proxies, not routed wirelength or timing.

Budgets are nearest-rank p25/p50/p75 of the earlier 20-layout sensitivity sample per case; the primary table uses p50. They are research anchors, not product limits. All methods share 16 initial queries within a 64-query allowance.

| Case | Candidate / baseline | Span budget (mm) | Paired temperature gain (K), median [range] | Both attained | Win/tie/loss |
| --- | --- | ---: | --- | ---: | --- |
| ascend910 | sa / random | 31.7516 | +0.0000 [-0.0563, +0.1239] | 5/5 | 1/2/2 |
| ascend910 | nsga2 / random | 31.7516 | +0.0000 [-0.0238, +0.0416] | 5/5 | 2/2/1 |
| micro150 | sa / random | 32.0000 | -1.4747 [-3.4346, +1.9120] | 5/5 | 2/0/3 |
| micro150 | nsga2 / random | 32.0000 | +0.3490 [-3.1015, +2.2197] | 5/5 | 3/0/2 |
| multigpu | sa / random | 29.6296 | +0.3228 [-0.0060, +2.0544] | 5/5 | 4/0/1 |
| multigpu | nsga2 / random | 29.6296 | +0.8233 [-1.2689, +2.8246] | 5/5 | 3/0/2 |

| Case | Candidate / baseline | Temperature cap (C) | Paired span reduction (%), median [range] | Both attained |
| --- | --- | ---: | --- | ---: |
| ascend910 | sa / random | 77.1343 | -0.5406 [-8.3724, +0.8163] | 5/5 |
| ascend910 | nsga2 / random | 77.1343 | +0.6980 [-3.3265, +3.1712] | 5/5 |
| micro150 | sa / random | 113.4063 | -1.4085 [-20.3883, +17.6955] | 5/5 |
| micro150 | nsga2 / random | 113.4063 | +6.1033 [-11.8143, +18.9300] | 5/5 |
| multigpu | sa / random | 102.2476 | -6.0150 [-19.7719, +15.9851] | 5/5 |
| multigpu | nsga2 / random | 102.2476 | +0.3759 [-3.9841, +8.4507] | 5/5 |

Positive values favor the candidate. Numeric summaries include only pairs where both attained the constraint; missing attainment is never zero gain. JSON retains all three anchors, each paired value/status, selected layout query indices, actual temperature AND span, checkpoint profiles, completion status, auxiliary HV and effort. A selected query index refers to the corresponding case/method/seed record in the source evidence.

HV summarizes Pareto coverage only. Separately best temperature and span are not a feasible joint design. Wall times are observations under workstation load, not controlled algorithm speedups.
