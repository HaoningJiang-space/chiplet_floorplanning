# Preregistered ideal passive-channel mechanism experiment

Declared before the 96-run matrix on 2026-11-11. Analyzed local baseline:
`dd4aac8`; successful session-start fetch found origin/main unchanged at
`c124aa982eb97f49a7f4be907554c94436ace2d2`. Local-only; no push or remote CI.

## Question and scope

How much does retaining external magnetic energy change a channel's threshold
delay and its skew relative to a declared 3 mm clock channel, when every other
assumption is fixed? This is a reduced-model mechanism study, not a real PHY,
PEX recovery, calibrated pad or hardware timing-feasibility claim. No real clock
period or setup/hold requirement is introduced. Production STA remains unchanged.

Geometry follows the ideal parallel-plate approximation in the existing GPIO
case: width 10 um, metal thickness 1 um, spacing above an ideal continuous return
plane 1 um, epsilon_r 3.9, nonmagnetic dielectric, rho 1.68e-8 ohm m.
Use R'=rho/(w*t), C'=epsilon*w/h, external L'=mu*h/w, G'=0. All coefficients
are positive constants. RC sets L'=0; RLC retains that external term. Return-plane
resistance, internal inductance, fringing, dispersion, skin/proximity loss,
dielectric loss, bumps, coupling and nonlinear IO are not represented. Finite
conductor thickness/width mean this is a declared coefficient model, not an exact
Maxwell solution for the drawn cross-section. Neither model is hardware qualified.

## Fixed boundaries and matrix

12 cases: length {1,3,6} mm x Thevenin resistance {25,100} ohm x source 10–90%
linear slew {100,600} ps. This source is constructed, not extracted from a loaded
pad waveform. VDD=3.3 V; rise starts at 1 ns, fall at 4 ns, stop at 8 ns. Each full
linear ramp lasts slew/0.8. Start at DC rest (zero voltage/current).
The receiver is a constant 1.117215037 pF capacitor, declared from the prior
Liberty pin value; that value is not a dynamic receiver calibration.

Reference planes are the near and far endpoints of the ideal wire. The source
resistor is outside the wire, receiver capacitor after its far endpoint. Each
ladder uses N={8,16,32} identical series sections, with half wire capacitance at
each endpoint and full capacitance inside. Add the receiver capacitance once.
Both models share the same shunt capacitances and series resistance. Zero-volt
branch-current probes store/dissipate no energy. No pad parasitics are added.

For each case/model/N, ngspice 42 runs at maximum step 0.5 ps; N=32 also at
0.25 ps: **96 runs**. reltol=1e-7, abstol=1e-14 A, vntol=1e-9 V, trapezoidal
integration, isolated spinit, no PDK/compatibility setting. Freeze source/deck,
executable, runtime DLL hashes, Python/numpy/scipy versions and gates. Keep
waveforms/logs, including failures; gzip is lossless and round-trip hash verified.

## Independent equations and conservation

With incidence B (+ upstream, - downstream), write

`C dv/dt = e0 (u-v0)/Rd - B i`, `L di/dt = B^T v - R i`.

For RC eliminate i=R^-1 B^T v. Solve these state equations independently from
the SPICE netlist with matrix exponentials and piecewise-linear forcing using
[SciPy lsim](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.lsim.html).
Use a 0.125 ps uniform output grid including every source breakpoint. Compare
both endpoint voltage waveforms and every 10/50/90% crossing. This is independent
implementation of the same discrete circuit, not an independent physical model.

Check integral balances at **every recorded adaptive timestep**:

* Q=sum(C_i v_i), deltaQ=integral(i_source).
* Each C_i delta v_i=integral(e0 i_source - B i)_i.
* E=1/2 sum(C_i v_i^2)+1/2 sum(L_j i_j^2).
* deltaE+integral(Rd i_source^2+sum(R_j i_j^2))=integral(u i_source).
* Also report the channel ledger, using v0*i_source and excluding driver loss.

Include finite end stored energy; returning energy/negative source power is
allowed. The analytic passive energy identity establishes the model's passivity,
not hardware fidelity. The finite ladder is an ordinary causal dynamical system;
it does not exactly reproduce the continuum's finite wavefront. Quiet initial
conditions are checked without making a Maxwell propagation-accuracy claim.

An independent uniform distributed-line reference uses z=R'+sL', y=sC',
gamma=sqrt(z*y), Zc=sqrt(z/y), A=D=cosh(gamma*l), B=Zc*sinh(gamma*l),
C=sinh(gamma*l)/Zc, and H=1/[A+B*s*CL+Rd*(C+D*s*CL)]. Compare frequency
responses at {0.01,0.1,1,3,10} GHz. Also compare the MNA response with separately
cascaded symmetric pi-section ABCD matrices. No |H|<=1 condition: a passive
network can have resonant voltage magnification. These sampled points do not
establish a continuous bandwidth or a time-domain error bound.

## Predeclared numerical screens

Maximum, over the whole transient, normalized total charge residual <=1e-5
(normalizer Ctotal*VDD), local-node charge residual <=1e-3 (Ci*VDD), energy
residual <=5e-4 (Ctotal*VDD^2). Oracle endpoint waveform difference <=0.33 mV,
every corresponding threshold crossing difference <=0.1 ps. Source stimulus
error <1e-8 V, driver Ohm-law residual <1e-10 A, initial rest <1e-12 in V/A.

Temporal N32 0.5->0.25 ps and spatial N16->N32 at 0.5 ps must each change
rise/fall 50% source-to-receiver delay and 10–90% slew by no more than
max(0.1 ps, 0.25% of the finer metric). The relative threshold is NOT based on
absolute event timestamps. N8->16 is also retained. Require unchanged crossing
counts/directions, and do not reduce multiple crossings to one scalar delay.
All 10/50/90% crossings of both directions within each source-edge window are
retained. Multiple crossings signal scalar timing ambiguity, not a violation of
passivity. Finite refinement differences are empirical screens, not error bounds.

MNA versus pi cascade: absolute complex H difference <=1e-9. N32 versus
continuum at the five specified frequencies: absolute complex H difference
<=5e-4 (additional screen specified before experiments, not a fitted threshold).
Failures remain failures; do not relax gates after inspecting results.

Negative ledgers on the fine 6 mm/25 ohm/100 ps RLC case: reversed source
current, omitted receiver charge/energy, duplicated receiver charge/energy,
omitted magnetic energy, reversed first-branch current. Each must fail at least
one conservation gate. Analytic one-capacitor RC waveform/energy tests, DC H=1,
zero-inductance limit and negative element rejection provide additional controls.

## Timing interpretation and next gate

Use same-edge source pairing: rise-data versus rise-clock, fall-data versus
fall-clock, with the clock fixed at 3 mm and identical driver/load/slew. This
is NOT the existing opposite-edge buffered/inverted GPIO lane. Define
skew=d_data-d_clock. For a fixed event mapping and all other timing terms held
constant, a change in skew contributes -delta_skew to setup slack and
+delta_skew to hold slack. Do not claim that one clock period or real interface
passes/fails. Equal 3 mm channels supply a common-effect cancellation control.

A hardware decision tolerance has not been sourced: report effects and numerical
screens only. Skin/return/bump/receiver and original characterization gaps remain
open. A later hardware-admission study needs independent channel evidence,
receiver switching/qualification criteria and a sourced setup/hold budget before
testing whether thermal/timing feasibility or placement ranking changes.

## Pre-run review

The existing ChatGPT research review, accessed with `codex-chatgpt-skill`, required
explicit G'=0 and shared coefficients, distinguishing the two numerical oracles
from hardware evidence, applying relative tolerances to delays rather than
timestamps, and refusing scalar slack for ambiguous crossings. Those requirements
are incorporated above before the matrix is frozen. This review did not execute
or independently reproduce the experiment. The review conversation is
https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865 .

## Separate numerical-method follow-up, declared before running

The original `matrix/` attempt completed 37 runs, all passing the declared
individual numerical gates, then the 3 mm/25 ohm/100 ps RLC N16, 0.5 ps case
exceeded its 180 s process limit. The first runner aborted on that exception.
That case's deck, prior 37 waveforms, progress report, frozen hashes and original
source snapshots are retained. Its captured stdout was not written by the old
exception path; mark that log missing rather than reconstructing it. The failure
mechanism has not been isolated, and is not evidence against channel physics.

Before any follow-up run, declare a new complete 96-run matrix in `matrix-gear/`
using ngspice Gear integration with maximum order 2. All circuits, cases, source
breakpoints, timesteps, independent matrix-exponential references and acceptance
thresholds above remain unchanged. Stream solver logs to disk and retain timeout
records so the matrix does not silently drop failures. Preserve the original
attempt, do not relabel it a passed 96-run experiment or combine integration
methods within a refinement pair. Gear's possible numerical damping is screened
by the same independent waveform/crossing and half-step checks; passing does not
make those finite numerical screens rigorous error bounds or hardware validation.

## Fast-edge refinement, declared after the Gear matrix and before new runs

The complete Gear matrix finished 96/96 runs; 69 passed the original per-run
gates. All 48 slow-edge records passed. The 27 failures are confined to the fast
edge: 24 RLC runs exceeded the endpoint waveform screen and three short RC coarse
runs exceeded the integral charge screen. Stable scalar timing is insufficient.

Keep that report unchanged. In `matrix-refined/`, rerun **all** six 100 ps
conditions, both RC and RLC, using maximum step 0.125 ps at N8/N16/N32 and
0.0625 ps at N32: 48 new runs. Reuse the 48 passed 600 ps records only after
checking exact deck bytes, solver/runtime/initialization hashes, unchanged
physics/oracle module and gates, measurement hashes and decompressed waveforms.
This supplies 96 analysis records, explicitly 48 new + 48 reused. Archive copies
may be immutable local hard links. Do not count reuse as new simulations.

All physical parameters, oracle grid and thresholds remain unchanged. The
0.125 ps oracle grid includes every source breakpoint; the comparison remains
a finite sampled waveform screen, not a continuous error bound. Compare spatial
and temporal changes within each case's own fixed numerical settings. Retain all
earlier failures; if further runs fail, retain them without relaxing the gates.
