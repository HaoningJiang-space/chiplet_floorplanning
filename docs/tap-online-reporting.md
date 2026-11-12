# Descriptive reporting for the fixed online pilot

Historical v4 reporting contract. For current physical-budget comparisons use
[R3 metrics](tap-r3-metrics.md) and `report_tap_physical.py`. Keep this old report
and its evidence intact; its HV summaries are now auxiliary interpretation.

This postprocessor adds no search or thermal changes to the running experiment.
It requires the complete 45-run verified evidence with successful policy replay;
partial evidence cannot produce comparative figures or summary statistics.
It checks exact case/method/seed coverage and paired initialization metrics.

Report each workload separately. The normalization is already frozen, and HV
values from different workload scales should not be averaged into a universal
winner. Publish the five individual paired HV differences against Random,
their minimum/median/maximum and descriptive win/tie/loss counts. Use 1e-10 as
the numerical HV tie tolerance, not as a significance criterion. Five paired
seeds do not establish broad superiority or a confidence interval.

Preserve capped trials at their actual query count and final attained quality.
Paired tables explicitly record whether both runs completed 64 queries. On
query-quality plots, aggregate a checkpoint only if all five trials reached it;
otherwise show individual traces, including each capped trial's actual endpoint.
Do not manufacture a 64-query point or average only the successful survivors.

The report also includes changes from the shared 16-query initial archive,
absolute temperature and centre-span improvements, elapsed seconds, proposals,
illegal-proposal fraction and the cache-hit fraction among legal evaluations.
The separately best temperature and span may occur in different layouts; their
marginal improvements are not a claim that one solution attains both. Cache-hit
rates do not by themselves measure a speedup. Actual cache timing still requires
a controlled proposal-stream ablation.

Pool all evaluated points within each workload to construct an empirical
reference front using the frozen temperature/span bins. Preserve every member's
method, seed and query index, including shared initialization points. This
front is not globally optimal and its number of points is not a method score.
Plot actual points without interpolating them into supposedly feasible layouts.

`report_tap_online_pilot.py` exports compact paired statistics and two PNG/PDF
figures: quality versus queries plus final quality versus elapsed time, and
absolute-temperature/centre-span archives. Synthetic test figures have an
explicit `SYNTHETIC TEST DATA — NOT EXPERIMENT RESULTS` banner and remain under
ignored local results; they are never published as experimental evidence.

After complete verification:

```powershell
python tools/report_tap_online_pilot.py --input docs/evidence/tap-online-pilot-v4.json --output docs/evidence/tap-online-pilot-analysis
```

Inspect the real rendered figures before publishing. Interpretation and the
next Chat review follow the complete paired results, not early completed seeds.
