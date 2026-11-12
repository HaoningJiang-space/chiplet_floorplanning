# Physical comparison replaces HV as the primary result

At session start, fetching origin succeeded and local/remote main both pointed
to `a7c2ad591435155da9cc4c535d22479ff6c56abb`; there were no new remote commits.
The user clarified that the actual question is which physical layout quantity
is better, not which optimizer diagnostic improved.

The implementation now leads with **minimum attained peak temperature under
the same interconnect budget**, and the reverse **minimum attained interconnect
cost under the same temperature ceiling**. The budgeted cost is currently the
demand-weighted mean chiplet-centre Manhattan distance in mm. It is not routed
wirelength or timing. [Exact definitions](tap-r3-metrics.md) specify joint point
selection, missing attainment, signs, units and paired aggregation.

Both policy APIs emit the new metric schema. The runner supports all five
methods, freezes three shared budget/ceiling anchors and reuses the first three
old initializations. The batch schedules only the two new methods, preserving
old baseline thermal evidence. The new reporter selects actual layouts and
records both objectives and a query index for every selected result. HV and
marginal extrema remain explicitly auxiliary. AGENTS and README now reflect
this priority. The historical v4 report and source evidence are preserved.

## What the existing experiments actually say

The [new table](evidence/tap-pilot-physical.md), [JSON](evidence/tap-pilot-physical.json)
and [figure](evidence/tap-pilot-physical.png) reanalyze **all 45 completed v4 runs**,
without additional thermal solves. All five original seeds are retained. The
anchors use nearest-rank p25/p50/p75 from the earlier sensitivity sample; their
selection is retrospective relative to v4 and frozen before new R3 runs.

At the primary p50 span budget, NSGA-II versus Random gives:

| Workload | Common span budget (mm) | Paired temperature reduction, median (K) | Range (K) | Both attained |
| --- | ---: | ---: | --- | ---: |
| Ascend910 | 31.7516 | 0.0000 | -0.0238 to +0.0416 | 5/5 |
| Micro150 | 32.0000 | +0.3490 | -3.1015 to +2.2197 | 5/5 |
| MultiGPU | 29.6296 | +0.8233 | -1.2689 to +2.8246 | 5/5 |

These are paired differences before taking a median. Positive means cooler.
They do not establish a universal winner. In particular, the earlier positive
Micro150 SA paired HV median does **not** imply lower constrained temperature:
at its p50 span budget, SA versus Random has median temperature reduction
**-1.4747 K**. The fixed-budget question can change the interpretation.

The reverse p50 temperature-ceiling comparison gives NSGA-II versus Random
median span reductions of 0.6980%, 6.1033%, and 0.3759% respectively. These
reverse results can select different layouts from the primary table. They are
not simultaneous gains to combine into one proposed layout.

The published figure shows every paired value at all three span anchors and
the median only when all pairs attain the constraint. It was visually checked.
No new seed or new physics calibration was required for this reanalysis.

## Local execution evidence and remaining experiment

- 319 unit tests passed, including joint-feasibility selection, raw boundary
  inclusion, no interpolation, unattained constraints, paired signs/percentages,
  missing pairs/capped trials and preservation of the old initializations.
- The documented two-chiplet CLI passed: 3 W, 34.1886 C; timing not run.
- One seed on Micro150 executed both new methods through the actual FV/HiTS
  path, 32 queries each, including the shared 16 initial states. These 64 new
  queries are **development-only**, not the full R3 comparison.
- Both new development policies were replayed with their saved thermal rows;
  all rows/events and TAP acceptance decisions matched. Nine old baseline
  trials (three methods x three cases, first seed) were replayed under current
  code with no additional thermal solves. Old search behavior is unchanged.

The [local receipt](evidence/tap-r3-physical-smoke.json) includes source hashes,
actual evaluated smoke points and their new metric summaries. The
[frozen R3 manifest](evidence/tap-online-plan-r3.json) and
[commands](tap-r3-protocol.md) are ready. The full 18-new-run comparison and
ATPlace pin-aware scale extension are not completed by this metric migration.
