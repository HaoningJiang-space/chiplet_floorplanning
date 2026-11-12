# OpenSTA timeout is incomplete evidence

The unified network runner now retains partial stdout/stderr and records
`execution_timeout` when OpenSTA exceeds its execution limit. It preserves
input and executable hashes, the generated circuit, RC records and log hash.
No timing-feasibility value is fabricated. The parent evaluation remains
`timing_unresolved`; an unresolved candidate cannot certify an optimum or
prove that the feasible set is empty.

A timeout was injected at the subprocess boundary of the real evaluator for
both reference and temperature-feedback analyses. Geometry, routing and heat
were still computed and retained. This is an injected failure test, not an
observed 120-second native timeout. A separate normal native run on identical
inputs completed both analyses and retained the previous feasible results.
[Evidence](evidence/local-sta-execution.json) records both outcomes.

Three regression tests cover partial byte output, normal nonzero exit versus
timeout, and exclusion from feasible-witness/empty-set proofs. Local milestone
validation passed 211 unit tests and the documented two-chiplet CLI case
(3 W, peak 34.1886 C; thermal uncalibrated, timing not run in that CLI case).
The native integrated control is the timing execution check.
