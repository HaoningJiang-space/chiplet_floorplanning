# R3 physical-budget comparison protocol

This stage compares layout quality using [shared physical ceilings](tap-r3-metrics.md).
The main result is peak-temperature reduction at a fixed demand-weighted mean
centre-span budget, not HV, proposal legality, or isolated marginal minima.

Use the original v4 three domains, package/power/cooling, FV/HiTS evaluator,
64 distinct thermal queries, 16 shared initial layouts, private caches,
10,000 proposal cap and original auxiliary HV scales. Reuse the first three
v4 seeds (2026111200..2026111202) without selecting by outcomes. Random, SA and
NSGA-II remain historical baselines; do not rerun their thermal evaluations.

Two new methods are the TAP-derived coordinate SA and NSGA-II conditional legal
mutation. Details are in [metrics and TAP acceptance](tap-r3-metrics.md) and
[the mutation definition](tap-r3-conditional-mutation.md). New-method order
alternates by seed. The full main batch is 2 methods x 3 cases x 3 seeds = 18
runs, at most 1,152 new queries. Start with one seed for implementation checks;
`--smoke-budget 32` marks those results as development-only and excludes them
from the complete comparison. Do not add more seeds without a concrete reason.

Freeze a new plan after executable code and this protocol are ready:

```powershell
python tools/run_tap_online.py --freeze --plan docs/evidence/tap-online-plan-r3-v2.json
python tools/run_tap_online.py --plan docs/evidence/tap-online-plan-r3-v2.json --hits ../HiTS --case micro150 --seed 2026111200 --method nsga2_legal --smoke-budget 32 --output results/r3-micro150-legal-smoke
python tools/run_tap_online_batch.py --plan docs/evidence/tap-online-plan-r3-v2.json --hits ../HiTS --output results/tap-online-r3
python tools/report_tap_physical.py --input docs/evidence/tap-online-pilot-v4.json --plan docs/evidence/tap-online-plan-r3-v2.json --batch results/tap-online-r3 --output docs/evidence/tap-online-r3-physical
```

The new plan binds source hashes, HiTS revision, original plan/evidence hashes,
copied initializations and p25/p50/p75 physical anchors from the earlier
sensitivity sample. The old v4 manifest is never rewritten to fit new code;
its exact reproduction uses its recorded old revision.

The checked-in `tap-online-plan-r3-v2.json` is already frozen: use it directly,
without rerunning `--freeze` onto the same path. It supersedes the original R3
manifest only to bind the post-review reporter addition of mutation enumeration
and filtering costs. Search, physics, thresholds, seeds and budgets are identical.
The original R3 manifest remains the source-bound record for development smoke
and retrospective pilot analysis; no thermal rerun is needed for this change.

The reporter checks new run geometry, original numerical invariants, objective
values, accounting, physical summaries and deterministic policy replay using
saved thermal results. It then combines 18 new records with 27 reused baseline
records. Preserve capped/exhausted local searches at their attained endpoints;
failed/unknown solves remain explicit and cannot produce a completed report.

Predeclared contrasts: SA/Random, NSGA-II/Random, TAP-SA/NSGA-II,
NSGA-II-legal/NSGA-II, and NSGA-II-legal/TAP-SA. Report all three ceilings,
attainment counts and per-seed differences. Missing attainment is not a numeric
loss of arbitrary magnitude. Three seeds support descriptive comparisons only.
Wall time includes geometry/mutation filters and thermal/reference checks; it
does not by itself establish a controlled speedup on a loaded workstation.

The same reporter can reanalyze all **45 original trials** without new solves:

```powershell
python tools/report_tap_physical.py --input docs/evidence/tap-online-pilot-v4.json --plan docs/evidence/tap-online-plan-r3-v2.json --output results/tap-pilot-physical-reanalysis
```

This is retrospective because the physical comparison anchors were chosen
after the pilot; it does not retroactively change that pilot's frozen protocol.
Preserve its original five seeds instead of silently discarding two.

Pin-aware larger ATPlace cases require a distinct metric contract and solver
domain. Current centre-span output must not be relabeled pin or routed length.
Real timing remains separate from these thermal/interconnect proxy comparisons.
