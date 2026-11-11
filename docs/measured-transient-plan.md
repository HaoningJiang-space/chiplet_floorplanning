# TTC transient follow-up, declared after failed steady-state admission

Base local commit `c5fc0a6`. Steady attempt remains `not_fitted`; do not relax
its thresholds. Raw observation: 13/26 long experiments stop high power near
100 C; others include residual drifts. The original endpoint audit has already
inspected all experiments, so the following held-out experiments are unused in
parameter fitting but **not previously unseen**. No model selection based on
their fit residuals has occurred.

Retain the same four calibration and nine prediction cases per cooling group.
No missing cooling time, 30-minute plateau, or higher equilibrium is invented.
Use actual measured power histories, including shutdown and post-shutdown
cooling. Predictions are conditional on those measured inputs: this does not
predict the protection controller, its cutoff time, or safe constant-power
operation. Natural and forced convection are still distinct systems.

Add only energy storage to the same 17-node network:

`C dtheta/dt + G theta = P(t)`,
`C = diag(C_cell repeated 16 times, C_bath)`.

All conductances and capacities must be positive. This guarantees a passive,
stable thermal response and permits the independent energy ledger
`sum(integral(P dt)) = delta(sum(C*theta)) + integral(g_a*theta_bath dt)`.
Spatially varying bath temperature, board parallel paths, nonlinear convection
and sensor lag remain unmodeled. Added capacities are equivalent network
parameters, not independently measured silicon/heatsink heat capacities.

Use the longest high-power interval already fixed by measured input. Start
60 s before its first sample (or index 0 if unavailable), through the end of
the recorded trace, including cooling. Work at native 0.1 s input spacing with
zero-order hold; observation residuals every tenth sample (1 s) plus the final
sample. No temperature interpolation. In each run initialize all 16 cell
temperatures at their measured first values. Initialize the unobserved bath
from zero **mean cell** storage at that instant:
`theta_b0 = mean(theta_cell0) - mean(P_first_1s)/g_z`.
This is an explicit initial-state assumption, not a fitted sensor offset.
Report initial bath temperatures, pre-step slopes and baseline spatial residuals;
bad initialization remains model discrepancy. No changes to measured ambient.

Solve using a symmetric generalized eigendecomposition of `G,C`, then exact
scalar exponential propagation for each piecewise constant input interval.
Verify the result against a separate full matrix exponential at selected small
controls, and audit integrated energy including initial/final storage. A solver
step refinement cannot recover unmeasured sub-sample input or sensor response.

Fit five log parameters by least squares, each run contributing its mean
per-sensor squared error (equal total run weights, not equal duration weights).
Original 3 conductance bounds/starts remain; capacity bounds are
`C_cell in [1e-4,10] J/K`, `C_bath in [0.1,10000] J/K` (computational bounds).
Append capacity starts `(0.02,100)`, `(0.1,1000)`, `(0.01,10)`, `(1,100)` to
the original four conductance starts respectively. Maximum 200 function
evaluations per start; xtol/ftol/gtol=1e-8. All starts/statuses/bound hits retained.
Keep full parameter sensitivity singular values and distinguish a numerically
identifiable reduction from physically identified material constants. No
statistical confidence intervals without the missing covariance budget.

Report calibration and held-out per-run temperature RMSE, max absolute error,
bias, spatial residuals and sensor peak. Also report errors with the same
frozen parameters under the alternative initial bath `mean(theta_cell0)`;
this is an initialization sensitivity scenario, not an uncertainty interval.
No physical-accuracy pass threshold is manufactured. The target chiplet, Pad
delay and package electrical channel remain unqualified irrespective of fit.

## Post-fit diagnostic declaration (not model selection or refitting)

The frozen fit has completed: fan C_cell reaches its computational lower bound;
worst sampled residuals approach 28 K. Preserve that fit and all original errors.
The reviewer emphasizes initial mean storage, unknown ambient drift and sampled
event timing. Ambient has only one reading per run; the result is conditional
on constant ambient, not proof that it was constant. In absolute temperature,
the varying-boundary equation would be `C*Tdot+G*T=P+sink*Tamb(t)`;
using relative temperature would additionally require `-C*1*Tamb_dot(t)`.

Without fitting anything else, audit all 26 cases at the native sampling grid:
report baseline, powered and cooldown residuals separately; report residuals
outside +/-1 s of the two principal power transitions (retain all-point errors);
shift the entire measured power sequence by +/-one sample (0.1 s), padding its
endpoint values, as timing sensitivity scenarios. They are not a certified
uncertainty bound and do not establish the logger's timestamp convention.
Report initial mean slope and `C_cell*slope/g_z` as an approximate bath-initial
correction; it is based on a 60 s trend, not an instantaneous derivative.
For both groups, sweep C_cell=[1e-4,1e-3,.01,.1,1] J/K with all other fitted
parameters fixed, on calibration cases only. This is an objective sensitivity
slice, not profile likelihood, a new fit, or a confidence interval.
