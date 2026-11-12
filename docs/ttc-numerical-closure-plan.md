# Frozen steady TTC numerical closure

This study follows the failed primary FV refinement in `ttc-spatial-results.md`.
It does not replace that experiment or select a mesh using measured temperatures.
The analyzed starting commit is `23b75c3`; origin fetch succeeded, with remote
`c124aa9` and no incoming commits. All computation is local.

Keep the source geometry, conductivity, finite active-layer volumetric source,
sensor coordinates, insulated side/bottom boundaries and uniform bath unchanged.
The 13 nominal power patterns and both cooling material sets are fixed. The
reference is the prior 1024-order continuous cosine solution; its last change
was 0.001291 K, a convergence diagnostic rather than a rigorous error bound.

Solve the same cell-centered FV equations by separation, retaining **all**
lateral discrete modes. For each axis, `L v = lambda D v`, with `D` containing
cell widths and `v.T D v = I`. The two eigenvalues add. Through thickness the
modal matrix has lateral diagonal `k dz lambda`, reciprocal half-cell interface
conductances, an insulated bottom and a top half-cell connection to the bath.
Source projection uses exact rectangle overlap. Source fractions along z are
the active-cell thickness fractions. Sensor observation is convex interpolation
at the same x/y coordinates and active mid-depth. The uniform bath contributes
`sum(P)/Ga` at steady state. Capacity is irrelevant to this DC calculation.

Before interpreting refinements, compare this solver with a separately assembled
3-D sparse solve, including nonuniform mesh/source mapping, local residuals,
total heat balance and the original primary grid. Check mass orthogonality,
eigen-equation residual, the analytic constant lateral mode, vertical residuals,
positive responses and source/sensor weight conservation. Replacing the computed
near-zero eigenvalue by exact zero must be guarded by a residual check; do not
clip negative nonzero modes or discard high modes.

Freeze five levels of maximum lateral pitch (micrometres):
`500, 250, 125, 62.5, 31.25`. Freeze active/bulk/pad subdivision counts:
`1/2/2, 2/4/4, 4/8/8, 8/16/16, 16/32/32`.
Run three sequences: lateral-only (z at level zero), depth-only (xy at level
zero), and coupled levels. Preserve every level. Report full and demeaned
sensor errors by pattern, worst sensor and elapsed time. A continuum-z impedance
on the discrete lateral modes provides a separate depth-error diagnostic; it
does not alter the FV solver or the declared observation operator.

The numerical screen requires the final coupled grid to differ from the fixed
continuum reference by less than **0.1 K** on every pattern/sensor and its last
refinement change to be less than **0.05 K**. Additional levels, if necessary,
may be chosen solely by these numerical criteria, with the extension recorded.
This screen supports only steady numerical consistency for this stack and
these observations. It does not validate the original coarse transient solver,
logger timing, physical materials, copper/air boundaries or any optimization.
No measured-error fitting, new material parameters, or physical rankings here.

ChatGPT web review is advisory; its corrections must be checked against the
actual equations and numerical controls. Keep this plan and code hashes in the
new result directory before computing nominal-pattern predictions.
