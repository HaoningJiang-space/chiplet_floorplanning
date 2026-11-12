# Layout quality at shared physical constraints

R3 comparison with predeclared physical anchors; historical baselines reused.

Primary: minimum attained peak temperature under a common demand-weighted mean centre-span budget. Reverse comparison: minimum attained centre span under a common peak-temperature ceiling. These are centre-distance proxies, not routed wirelength or timing.

Budgets are nearest-rank p25/p50/p75 of the earlier 20-layout sensitivity sample per case; the primary table uses p50. They are research anchors, not product limits. All methods share 16 initial queries within a 64-query allowance.

| Case | Candidate / baseline | Span budget (mm) | Paired temperature gain (K), median [range] | Both attained | Win/tie/loss |
| --- | --- | ---: | --- | ---: | --- |
| ascend910 | sa / random | 31.7516 | +0.0000 [-0.0238, +0.0000] | 3/3 | 0/2/1 |
| ascend910 | nsga2 / random | 31.7516 | +0.0000 [-0.0238, +0.0000] | 3/3 | 0/2/1 |
| ascend910 | tap_sa / nsga2 | 31.7516 | +0.0258 [+0.0000, +0.0468] | 3/3 | 2/1/0 |
| ascend910 | nsga2_legal / nsga2 | 31.7516 | +0.0000 [+0.0000, +0.0000] | 3/3 | 0/3/0 |
| ascend910 | nsga2_legal / tap_sa | 31.7516 | -0.0258 [-0.0468, +0.0000] | 3/3 | 0/1/2 |
| micro150 | sa / random | 32.0000 | -1.4747 [-3.4346, +1.9120] | 3/3 | 1/0/2 |
| micro150 | nsga2 / random | 32.0000 | -0.8379 [-3.1015, +1.4084] | 3/3 | 1/0/2 |
| micro150 | tap_sa / nsga2 | 32.0000 | -1.7126 [-3.4752, -0.3347] | 3/3 | 0/0/3 |
| micro150 | nsga2_legal / nsga2 | 32.0000 | +0.3740 [-1.2031, +0.4971] | 3/3 | 2/0/1 |
| micro150 | nsga2_legal / tap_sa | 32.0000 | +0.8317 [+0.5095, +3.8492] | 3/3 | 3/0/0 |
| multigpu | sa / random | 29.6296 | +0.1090 [-0.0060, +2.0544] | 3/3 | 2/0/1 |
| multigpu | nsga2 / random | 29.6296 | +0.8233 [-0.3668, +2.8246] | 3/3 | 2/0/1 |
| multigpu | tap_sa / nsga2 | 29.6296 | -0.8233 [-4.3006, -0.1331] | 3/3 | 0/0/3 |
| multigpu | nsga2_legal / nsga2 | 29.6296 | +0.1499 [-2.6027, +1.5176] | 3/3 | 2/0/1 |
| multigpu | nsga2_legal / tap_sa | 29.6296 | +1.6507 [+0.9732, +1.6979] | 3/3 | 3/0/0 |

| Case | Candidate / baseline | Temperature cap (C) | Paired span reduction (%), median [range] | Both attained |
| --- | --- | ---: | --- | ---: |
| ascend910 | sa / random | 77.1343 | -0.5406 [-4.0886, +0.8163] | 3/3 |
| ascend910 | nsga2 / random | 77.1343 | +0.6980 [-3.3265, +2.2026] | 3/3 |
| ascend910 | tap_sa / nsga2 | 77.1343 | +0.7985 [-4.8202, +4.0292] | 3/3 |
| ascend910 | nsga2_legal / nsga2 | 77.1343 | +1.3858 [+0.0614, +3.8515] | 3/3 |
| ascend910 | nsga2_legal / tap_sa | 77.1343 | -0.1852 [-0.7430, +5.9207] | 3/3 |
| micro150 | sa / random | 113.4063 | -1.4085 [-6.3291, +17.6955] | 3/3 |
| micro150 | nsga2 / random | 113.4063 | +6.1033 [-11.8143, +18.9300] | 3/3 |
| micro150 | tap_sa / nsga2 | 113.4063 | -23.3503 [-41.0000, -5.6604] | 3/3 |
| micro150 | nsga2_legal / nsga2 | 113.4063 | +8.1218 [-7.5000, +8.6792] | 3/3 |
| micro150 | nsga2_legal / tap_sa | 113.4063 | +23.7589 [+13.5714, +25.5144] | 3/3 |
| multigpu | sa / random | 102.2476 | +1.4085 [-9.5618, +15.9851] | 3/3 |
| multigpu | nsga2 / random | 102.2476 | +6.6914 [-3.9841, +8.4507] | 3/3 |
| multigpu | tap_sa / nsga2 | 102.2476 | -30.0000 [-49.4024, -14.5594] | 3/3 |
| multigpu | nsga2_legal / nsga2 | 102.2476 | -9.9617 [-30.0000, -7.9681] | 3/3 |
| multigpu | nsga2_legal / tap_sa | 102.2476 | +4.0134 [+0.0000, +27.7333] | 3/3 |

Positive values favor the candidate. Numeric summaries include only pairs where both attained the constraint; missing attainment is never zero gain. JSON retains all three anchors, each paired value/status, selected layout query indices, actual temperature AND span, checkpoint profiles, completion status, auxiliary HV and effort. A selected query index refers to the corresponding case/method/seed record in the source evidence.

HV summarizes Pareto coverage only. Separately best temperature and span are not a feasible joint design. Wall times are observations under workstation load, not controlled algorithm speedups.
