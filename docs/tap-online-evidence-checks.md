# Pilot evidence validation while the fixed experiment runs

The running v4 experiment is unchanged. `verify_tap_online_pilot.py` is a
separate postprocessor and does not modify frozen search, physical inputs,
initialization, proposal distributions, weights or hypervolume reference points.

For each terminal saved run it checks:

- Trial identity, plan hash, frozen implementation hashes, source HiTS commit,
  search seed and identical 16-layout initialization charged in order.
- Full geometry, unique canonical thermal states and sequential query indices.
- Source/mapped/removed power, numerical receipts, residual/reference checks,
  matrix invariants and consistency of saved peak temperature. These are
  numerical evidence checks, not independent physical calibration.
- Centre-span values recomputed directly from the source demand matrix and
  placement coordinates.
- Every event in order: a fresh query must introduce its exact saved layout;
  a cache hit must refer to a previously queried equivalent state, never a
  future result; rejected complete geometries must actually fail verification.
- Proposal/query/cache/rejection accounting, proper terminal budget/cap status,
  checkpoint placement in the query stream and nonnegative consistent timings.
- The numerical-bin archive and HV independently recomputed using vertical-strip
  integration rather than the online rectangle-addition implementation.
- With `--replay`, the unchanged policy is rerun against only that run's recorded
  objective values. Asking for an unseen state is rejected. All proposal events,
  cache hits, rejected candidates and generation counts must match. This checks
  trace reproducibility, not independent reimplementation of each optimizer.

The default summarizer refuses an incomplete batch. `--partial` is explicitly
diagnostic: it validates only terminal trials already registered by the live
batch and emits no aggregate method comparisons. It neither restarts the batch
nor treats an incomplete/unknown trial as infeasible. Capped runs remain in
final summaries with their actual query counts and statuses; final-score
summaries must not be mislabeled as all having completed 64 queries.

Negative tests alter cache references, power, objectives, metrics and completion
counts to confirm rejection. A known two-rectangle example checks the separate
HV integration. The first actual terminal pilot trial was validated and its
policy trace replayed while the remaining trials continued locally.

Full verification command after the batch finishes:

```powershell
python tools/verify_tap_online_pilot.py --root results/physical-calibration/tap-online-pilot-v4 --plan docs/evidence/tap-online-plan-v4.json --output docs/evidence/tap-online-pilot-v4.json --replay
```

Do not interpret the first completed seed as evidence of a method winner. Keep
the complete paired five-seed results, failed/capped outcomes and run costs for
the next Chat review.
