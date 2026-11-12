# Chat guidance at the algorithm transition

The existing Chat/Thinking session completed a GitHub-only review of
`018a1bde63c38c1e909af634ef97022b1ad78ee9`, covering six commits after
`da65fe96f0676621d14e86fbfeb8852f229816d9`. The reviewer reported reading
the complete oracle and all 360 query traces and independently checking their
best queried scores and 18 summary groups. It accepted the reference experiment,
but found no robust winner. This is review, not independent execution of HiTS,
the local tests, or the CLI.

The user explicitly prioritizes algorithms. Keep the common FV/HiTS model and
physical invariants; measured calibration and manufacturing signoff are not
prerequisites. IHP access work remains a separate external-validity study.

## Findings and disposition

- The current single-chip move changes a chip's complete position/orientation
  state, possibly both at once. A local recount confirmed 206 edges: 52
  position-only, 83 orientation-only, and 71 joint. Preserve the original results,
  but separate atomic and joint moves in the next protocol and ablation.
- The reviewer reported atomic components of 68, 8 and 1 thermal classes,
  versus a connected 77-class joint graph. Its full-state counts were
  4,352 + 512 + 64 versus 4,928 connected. These connectivity counts still need
  a reproducible local audit before being used as new experimental evidence.
- Strict floating-point Pareto dominance spuriously distinguishes classes 0
  and 76. Their temperature difference is 3.93e-11 K and centre spans are equal;
  the local oracle confirms this. Introduce an explicit numerical tie policy
  and objective-space deduplication without rerunning HiTS.
- Distinct-query accounting is valid for the saved offline experiment. Online
  comparisons must also report proposals, legality checks, cache hits,
  assembly/solve counts and total elapsed time.
- Joint moves are not by themselves novel. Compare against mature
  move/swap/rotate search and a standard multiobjective baseline under the same
  evaluator, legal domain and budget before claiming a contribution.

## Research priorities and guidance cadence

First correct and freeze the evaluation protocol. Then use three original TAP
workloads and larger independent domains for a bounded online pilot. Compare
random search, strong floorplanning SA and NSGA-II. Verify representation/domain
compatibility rather than assuming identical feasible sets. Freeze starts,
budgets and Pareto reference conventions before comparative outcomes. Use
identical proposal streams for a separate cache timing ablation.

Ask Chat at protocol freeze before the main pilot, completion of the three-case
pilot, and completion of move/cache ablations. Push verified milestones first.
Continue local-only experiments and GitHub-only review, without uploads or
additional Chrome permissions.

The user subsequently questioned the small thermal span: only 0.97688 K across
77 classes, against approximately 32 K peak rise above ambient, while the
coolest layout increases centre span by 49.5%. Diagnose larger-domain layout
sensitivity before scaling algorithm comparisons, without changing source
power or tuning weights to manufacture a tradeoff. The narrow domain and
common package resistance are possible explanations, not established causes.
Chat's completed follow-up recommends a bounded diagnostic: 20 preselected
distinct legal layouts from the larger domain, plus six individual heat-source
solves at each of a hot, cold and middle reference layout (about 38 solves).
Keep geometry/materials fixed during each source decomposition, and sum fields
at the same total-field hotspot; maxima cannot be added. The approximately
32 K total peak rise must not be labeled a common package rise without this
decomposition. A small sampled range cannot prove the entire large domain is
insensitive. If sensitivity remains weak, consider thermal constraints with
communication optimization rather than forcing a peak-temperature narrative.
This diagnostic is guidance, not a completed experiment.

Review session: https://chatgpt.com/c/6af55ac1-8880-83e8-adbc-f1650608f447
