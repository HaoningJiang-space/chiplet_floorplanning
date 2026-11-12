# Frozen TTC spatial falsification, 2026-11-11

Start HEAD `7cc3371`, clean, successful fetch: origin `c124aa9`, ahead 9/behind 0.
Previous goal turn made progress (source evidence, 26-run observations and two
commits). The full ten-metric research goal remains active; no SOTA claim.

## Hypothesis and limits, fixed before new predictions

Does a spatially resolved, source-geometry internal network improve the sensor
differences left unexplained by the 17-node reduction? This is a **hybrid
diagnostic**: retain previously fitted dynamic sink G_a and C_b, replace the
internal 16-cell network with source geometry/materials. Spatial resolution,
internal total capacity and transfer function all change together. This does
not isolate one causal parameter or reproduce the complete 3D-ICE heatsink.
No new parameter fit, lag shift or residual smoothing is allowed in this run.

Author source geometry/materials remain as locked in `ttc-upstream.lock.json`.
Additional pinned parser/die files verify layer order. In coordinates increasing
from bottom to top: active Si 15 um (heat sources and sensors), bulk Si 610 um,
silicone pad 500 um, then a **spatially uniform but time-varying** bath T_b(t).
The bath is a dynamic node: C_b dT_b/dt = sum(contact heat) - G_a(T_b-T_air).
It is not a fixed-temperature boundary. The outer active face and all sidewalls
are adiabatic. Each connection includes half the thickness of both adjacent
volumes; pad-to-bath includes the remaining half-pad resistance, with no added
contact resistance because the source pad conductivity already includes contact.
No copper spreading or fin/air advection is represented by this lumped boundary.

Use source-fitted Si k=88 and pad k=14.3/20 W/(m K), source volumetric capacities,
and the exact 32 heater rectangles / 16 sensor coordinates. Sources distribute
by physical overlap area, half power per heater. Heat capacity is Cv*volume,
not a fitted per-node value. Active-layer sensor interpolation uses physical
coordinates within continuous silicon, with convex weights summing to one.
T_air is the per-run CP11 number; its time history remains unknown.

Primary mesh: all heater edges retained; subdivide feature intervals to maximum
500 um in x/y, 1 active / 2 bulk / 2 pad depth cells. This mesh is chosen before
measured predictions. Numerical controls: coarser 1000 um, finer 250 um x/y;
depth refinement 1/4/4 at fixed primary x/y. Refined grids are diagnostic and
cannot be selected because of lower measured errors. If convergence fails,
retain that failure and do not qualify the spatial prediction.

## Computation and controls

For constant properties solve C dtheta/dt + G theta = B P. Exact generalized
eigenmode propagation retains all modes; no model reduction or thermal time
step fitting. Chunk input processing to bound memory. End-of-interval output
only, as source-selected previously. Integrate energy analytically for all
input intervals, including the last. Independent backward Euler at 0.01,
0.005, 0.0025 s on short synthetic steps verifies time behavior and permits
large refined-mesh comparisons without dense diagonalization.

Before measured comparison: (1) one-dimensional uniform-source continuum limit
under depth refinement; (2) independent Kronecker Laplacian/series-resistance
assembly; (3) positive C, symmetric reciprocal G, nonpositive off-diagonals,
anchoring and conservation; (4) per-channel source weights and sensor mapping;
(5) local residuals and layer interface flux continuity; (6) symmetric physical
patterns and sensor permutations; (7) mesh convergence on all 13 nominal power
patterns and switch transients. Numerical screen: sensor changes <=0.1 K on
last refinement, additionally smaller than 10% of any claimed measurement
improvement. Failing this is retained, not repaired by retuning materials.

## Identical measured-case contract

Use the previous 26 runs, same selected raw start/end and actual native 0.1 s
V*I histories. No exclusions in primary metrics. Previous 8 calibration / 18
held-out labels are descriptive: all data have now been seen; no blind test.

To compare unmeasured internal states fairly, form each model's stationary
field under the first one-second mean power, then add a common offset to all
nodes so its initial mean of 16 sensor predictions equals the first measured
sensor mean. This is conditional initialization, not a measured internal state.
Apply the same rule to the frozen 17-node model and the spatial model. Retain
the previous per-sensor initialized 17-node result as a separate baseline.
Report first 60 s, remainder, all time, spatial differences, common residual,
and +/-1 s around both main switching events separately. For initialization
sensitivity, also use a uniform first-measured-mean initial field for the same
models; do not optimize its temperature or choose between initializations.

Primary falsifiable screen: at least 20% lower equal-run held-out spatial RMSE
in **each** cooling group, and improvement in at least 7 of 9 held-out patterns
per group, beyond the numerical screen. This is an investigator-set effect
threshold, not a material/measurement uncertainty model. Common-mode and total
errors are reported even if they worsen. Event peaks cannot be discarded.

ChatGPT design review requested identical initialization, explicit dynamic bath,
layer heat accounting and a prespecified spatial improvement test; these are
included. Its review is advisory. Physical qualification stays false throughout.
