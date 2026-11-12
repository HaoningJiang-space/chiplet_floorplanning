# Review follow-through: decision evidence and cache provenance

The user supplied a substantive review through `51af110`. Separately, the
existing ChatGPT reviewer completed GitHub-only review of the 25 commits from
`c124aa9` to `92c2835`, after publication made them accessible. It inspected
commit lists/available patches and key final sources; four large evidence JSON
patches were unavailable and their HEAD contents were read instead. This is
source/report review, not independent execution of the large local experiments.
The complete parent chain through `92c2835` has 39 commits. Subsequent `51af110`
contains level-2 evidence and workflow documentation, not a solver change.

## Independently recomputed decisions

`tools/audit_research_decisions.py` reads the original published v0.7/v0.8 and
level-2 evidence, records its hashes, and recomputes rather than copying the
user's derived decisions. No simulator or parameter fit is run by this audit.

The existing timing penalty already used electrically admitted candidates as
its thermal baseline; the research-gates prose described a broader set. That
documentation mismatch is corrected. New explicit statistics separate:

- G: evaluated geometry/routing-legal candidate pairs;
- E: G after electrical admission;
- T: E after setup/hold checks.

Costs are `min(E)-min(G)`, `min(T)-min(E)`, and `min(T)-min(G)`. Empty subsets
produce null costs, not zero. These minima concern the evaluated portfolio;
unknown search results do not prove the full physical design space infeasible.
A missing shortest-route witness now reports `routing_search_failed`, rather
than incorrectly labeling the search outcome as an invalid routed geometry.

| Policy | G | E | T | Electrical cost / K | Setup/hold cost / K |
|---|---:|---:|---:|---:|---:|
| R1 | 27 | 27 | 27 | 0 | 0 |
| R2 | 27 | 20 | 20 | 0 | 0 |
| R3 | 0 | 0 | 0 | undefined | undefined |
| R4 | 27 | 27 | 27 | 0 | 0 |

R3 only rejects the evaluated fixed routes; R1 gives legal alternatives. The
old zero incremental-timing-cost results remain unchanged. Hand-worked controls
separately exercise a 5 K electrical cost plus 5 K setup/hold cost, empty sets,
unknown search and invalid numerical/status inputs. They are software controls,
not real-design positive examples.

Across the six thermal profiles and 27 fixed candidates, layout 26 has minimum
maximum regret 0.0835617 K. Layout 23 has 0.296778 K; layout 20 has 1.209574 K.
The latter two are named comparisons, not necessarily second/third place.
This finite thermal-table decision remains robust in that limited sense despite
a rank reversal. It does not establish continuous-parameter robustness,
temperature-dependent interface feasibility, or physical calibration.

For natural P at level 2, recomputing `1 - RMSE / U_continuum_RMSE` yields
19.1891% improvement for raw FV and 20.6425% for the corrected estimate. Both
improve 8/9 held-out patterns. Only the correction crosses the 20% screen; the
spatial convergence screen still fails. Finer numerical solutions need not
move closer to measurements when model assumptions remain uncertain.

## Confirmed cache-admission gap and existing-result check

ChatGPT identified a real provenance gap in `audit_ttc_package_transient.py`:
the prior-cache check excludes the driver hash, even though that driver defines
part of the control protocol. The risk concerns future reuse after protocol
changes; the finding alone does not invalidate existing BE arrays.

`tools/audit_ttc_cached_reference.py` independently checked the frozen v1/v2
driver copies, dependency hashes, physical inputs, mesh descriptions, cached
array hashes and exact reused BE/Richardson arrays. It compares normalized
control-function syntax, accepting only the specific known cache-loader adapter
and the relocated metadata write. Pulse and flux-check functions are compared
in full. All four reused level-0 bundles match. Tests reject changes to power
ordering, time steps, sampling and the cache adapter.

This is a retrospective check, **not yet a mandatory cache-admission guard**.
The running v2 job retains its frozen source and may finish. New cache-reusing
runs are prohibited by project instructions until the driver integrates a
mandatory protocol fingerprint. That integration remains the next engineering
fix; do not present this audit as having already fixed the runner.

## Next evidence, in dependency order

1. Finish the unchanged steady level-3 and transient level-1 runs. Then isolate
   the slower P-C refinement around pad extension, material interfaces, source
   edges, thickness and sensor interpolation. Use at least three spatial levels
   with the same geometry/materials. Add independently converged field-hotspot
   and prospective critical-device observations; sensor agreement alone does
   not certify unmeasured maxima. Keep common residual, spatial residual and
   between-grid differences separate. Do not fit away discretization error.
2. Close one data/forwarded-clock interface contract at fixed process, voltage,
   operating mode, input waveform, reference planes and loads before adding
   temperature points. Preserve the Pad mismatch. If original assets cannot be
   recovered, any abstract-interface study must remain explicitly conditional.
3. Freeze a small enumeratable placement-route domain and source-supported
   constraints. Report electrical and incremental timing costs separately;
   toggle temperature feedback in matched cases and preserve the zero-cost
   control. Expand the current boundary-optimum candidate grid before choosing
   an optimizer. Never use extra positive slack ranking as evidence of necessity.
4. Only then compare thermal-first, timing-first, alternating and joint search
   with the same evaluator, domain, budgets, seeds and infeasible-case accounting.
   Report decision loss as well as ranks. No SOTA claim is established here.

Local validation after these changes: 175 unit tests pass, including the
independently invoked cache-protocol tests. The basic two-chiplet CLI passes
with 3 W and 34.188607 C; it still reports thermal uncalibrated and timing not run.
The earlier large experiment records were not regenerated by this bookkeeping
change, and their preserved historical schemas/results remain unchanged.

Reproduce the two audits locally:

```
python tools/audit_research_decisions.py --output PATH_TO_OUTPUTS
python tools/audit_ttc_cached_reference.py --prior results/physical-calibration/ttc-package-transient-v1 --current results/physical-calibration/ttc-package-transient-v2 --output results/physical-calibration/cache-protocol-audit-fresh.json
```

Tracked receipts are `evidence/local-research-decisions.json` and
`evidence/local-ttc-cache-protocol-audit.json`. Review conversation:
https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865.
