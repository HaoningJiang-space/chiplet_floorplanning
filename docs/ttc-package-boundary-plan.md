# Frozen explicit-package steady diagnostic

Starting checkout `a87e529`; origin fetch succeeded and remains `c124aa9`.
All simulations and Git commits stay local. This is a boundary-hypothesis
diagnostic, not a new fit, author-code reproduction or hardware qualification.

Read the pinned HS483 and HeatsinkBlocks sources before implementation. The
source geometry is a 10.24 mm square silicon die (15 um active + 610 um bulk),
0.5 mm silicone pad, 60 x 60 x 2.8 mm copper base, and 23 fins of thickness
0.5 mm, height 19.2 mm and length 60 mm along y. The real pad is 27 mm square;
the author's validation model crops it to the die footprint. Copper k=401 W/mK.
Fin x positions are taken as centers of 23 equal base strips: an inference
from the author's discretization, not an independently measured placement.

Use the source natural h=2.8 W/m2K and source fan correlation at 2700 RPM.
Convert RPM to rad/s exactly using 2*pi/60; the upstream 1/9.55 conversion is
rounded. Keep the difference visible. The source velocity relation is
`v = omega * 5.98e-5 * 0.9 / 8.31e-3`; the fan h correlation is
`0.8793*(11.8+9.33*v-1.09*v*v)`, valid v=1..4.1 m/s (natural v=0 separately).
Only the two broad fin sides exchange heat with a spatially fixed air ambient.
Tip/end/base-exposed/remaining pad faces are insulated. Air warming, radiation,
clamping/contact variation and external convection remain unvalidated assumptions.
The inherited pad conductivity already includes fitted contact effects; do not
add a second fitted contact resistance. No material is re-estimated.

Implement a full 3-D reciprocal finite-volume network. Use a **shared conforming
Cartesian xy partition** cropped to each body's actual footprint; face-neighbor
centers are collinear with the face normal. The initially considered nonmatching
two-point overlap connection was not adopted: conservation alone would not prove
consistency when centroids are laterally offset. Reject nonmatching interfaces.
Include both half-cell resistances at every material interface; broad fin-side
convection includes the center-to-surface half-cell resistance and 1/h in series.
This latter convention is physical center-to-face conduction, not a byte-for-byte
reproduction of the upstream lumped fin expression. Keep all raw physical solves.

Three configurations: U = die and cropped pad with fixed-temperature top;
C = cropped pad + explicit copper base/fins; P = full 27 mm pad + copper/fins.
Use identical die mesh/source/observation coordinates across U/C/P at each level.
The shared axes retain heater, die, full-pad and fin footprint edges; subdivide
inside die by 500/250/125/62.5 um and outside by 2000/1000/500/250 um.
Depth counts active/bulk/pad = 1/2/2, 2/4/4, 4/8/8, 8/16/16;
base = 2/4/8/16 and fin height = 4/8/16/32. Keep every level; extend only on
numerical evidence, never on measured-error improvement. Use CG with a symmetric
AMG preconditioner and verify actual residual and heat balance; compare a small
system against direct factorization. Reuse failed or completed jobs only by
explicit resume with verified input/code hashes.

First verify constant/affine interface fields, a one-dimensional layered
resistance, nonnegative conductances, symmetric G, positive capacity, exact power
weights, conservative interfaces and the U solution against the independent
separated solver on the **same axes**. Compare U to the continuum separately.

Report the raw FV solution and the transparent numerical correction
`R* = R_U_continuum + (R_C_or_P_FV - R_U_FV)`. Both have the same continuum limit
if the grids converge. The correction removes the known uniform-model error,
but is not an exact package solution or a rigorous error bound. Preserve its
assumption that remaining boundary-response error converges under refinement.

For each boundary contrast (C-U and P-C), report the absolute and demeaned
sensor responses on all 13 nominal power patterns. Require the last change in
demeaned contrast below 0.02 K and below 10% of its maximum spatial effect to
interpret its magnitude. A small/zero effect may fail the relative screen;
report it as unresolved rather than divide by zero or relax the gate. Examine
raw and corrected convergence separately; do not infer full convergence from
the correction alone or add maxima of separate errors.

Keep the previous 26-run 9-second approximate-DC windows, measured source
powers, source materials and training/held-out labels fixed. Compare spatial
temperature differences only. A small window drift does not prove that the
larger copper/fin structure is fully steady; preserve this limitation.
Report all cases, with the approximately 48 W `sixteen` pattern explicitly
outside the source <40 W domain. The earlier >=20% RMSE improvement and >=7/9
held-out pattern thresholds are applied to C/P versus the U continuum for this
new boundary-hypothesis diagnostic. The reduced 17-node baseline is retained
separately; the earlier primary experiment's result is unchanged. Additionally report the domain-eligible
8 held-out patterns separately (no new success threshold). The baseline and
U-continuum errors must reproduce the previous DC report. No SOTA or physical
calibration claim is licensed by this experiment.

Freeze plan/source/code hashes before nominal or measured predictions. ChatGPT
reviews are advisory, with mathematical objections independently checked.
