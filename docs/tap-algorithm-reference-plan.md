# First algorithm experiment: exact small-domain reference

The user requested a shift from physical admission to algorithms. Freeze this
experiment before evaluating the 77 temperatures. Use the existing six-chip
Ascend domain, FV/HiTS thermal contract and 77 thermal classes; do not wait for
completion of the separate IHP detailed-access work. That work does not silently
change the evaluator. The existing aggregate-routing class cover supplies an
existential graph witness for every class, not physical routing qualification.

Compute one canonical thermal evaluation per class with the existing local HiTS
routine. Preserve all 77 results, including admission failures; a failed solve
must not be converted to a temperature penalty. This gives an exact finite-domain
reference under the fixed discretization, not a continuum or physical optimum.

The second objective is mean demand-weighted Manhattan **centre span**, in mm.
It is a placement communication-distance proxy, not routed wirelength, a Pad
distance lower bound, delay or bandwidth. This quantity is also constant under
the declared half-turn thermal equivalence. Report the full two-objective Pareto
set instead of inventing a tighter timing constraint to produce a conflict.

Compare uniform random search without replacement, multistart local descent,
and simulated annealing. All start at class 0 and use the same legal class set,
evaluator, cache and budgets of 8, 16 and 32 distinct thermal queries, with seeds
0..19. A local move changes one chip's centre or canonical shape orientation.
Report connected components of this move graph. Both local methods restart at
an unqueried random class after 32 proposals with no new query, or immediately
if no neighbour exists; restarts count toward the query budget. Proposals and
restarts are recorded separately. No global objective information guides them.

Evaluate two fixed scalar objectives: normalized temperature rise alone, and
the equal-weight average of normalized rise and centre span. Normalize both by
their class-0 value, not by an oracle optimum/range. Annealing temperature falls
geometrically from 0.1 to 0.01 over the query budget. These are declared baseline
settings, not tuned algorithms or SOTA claims.

For economical exact comparison, first build the complete oracle locally, then
replay algorithms through a query-counting interface. The oracle cost is reported
separately and not hidden as free algorithm runtime. Measure optimum hit rate,
best objective gap and proposals under equal distinct-query budgets. No speedup
claim follows from cached table lookup time. Closely spaced thermal rankings
remain subject to discretization uncertainty; publish the gaps.

Next extend successful baseline machinery to larger independent domains and the
other two source workloads with online HiTS evaluations. Only then evaluate
search improvements and ablations against these same-model baselines. This
first experiment is an algorithm reference, not completion of the physical
benchmark or justification for a new optimizer.
