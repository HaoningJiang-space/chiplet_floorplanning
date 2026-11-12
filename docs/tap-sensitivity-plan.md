# Bounded layout sensitivity diagnostic

Freeze before new temperature evaluations. Respond to the user's observation
that the 77-class Ascend span is only 0.97688 K. Keep original source powers,
the FV/HiTS contract, 64-base conformal mesh and all cooling/material parameters.
Do not change weights or power to amplify a result.

Select 20 distinct canonical states per original workload using seed 20261112.
Use the complete per-chip centre-grid/four-rotation domain, sequentially placing
chips in shuffled order and choosing uniformly among candidates legal against
the placed prefix. Retry an incomplete construction, with a 10,000-attempt cap.
This is deliberately a bounded exploratory sample, NOT uniform over all legal
layouts and not a global temperature range estimate. Save every placement in
the plan before thermal evaluation. A solver failure stops the run rather than
replacing the sample. All three workloads use identical sampling rules.

For Ascend, select the coldest, median-rank and hottest rows of the existing
77-class oracle (sort by peak, then class index). Recompute their full fields,
then solve each of six individual source contributions with all other source
powers zero. Keep every die, material and boundary in place; require identical
operators. Sum temperature-rise fields, not separately located maxima. At the
total-field hotspot report its owning die's contribution and all other sources.
Check field superposition within 1e-6 K and RHS superposition within 1e-10 W.
These checks verify attribution, not measured physical calibration.

Total: 60 sampled full-power solves, three reference-field solves and 18
single-source solves. Existing direct/residual/energy checks remain unchanged.
Report all samples, ranges and centre-span proxies. A larger sampled range
proves the old small domain missed thermal variation. A small sampled range
does not prove the whole large domain insensitive. Do not claim practical
thermal significance solely from a nonzero numerical difference.

Next choose whether to emphasize peak-temperature optimization, Pareto tradeoffs
or communication optimization with thermal constraints based on these results.
The diagnostic does not establish a new optimizer or a universal threshold.
