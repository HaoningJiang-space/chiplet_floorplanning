# Physical consistency before optimization

The user's governing requirement is that research obey physical laws. A small
numerical residual or agreement with a Liberty table does not establish that
the modeled system represents the intended chiplets. We distinguish three
questions: are the equations physically consistent; do we solve those equations
correctly; are their parameters, boundary conditions and approximations valid
for the proposed hardware? All three matter. The last question remains open.

## Thermal system

The present steady model discretizes conduction with positive conductivity,
positive contact resistance and convection to a specified reservoir. For each
edge, `q_ij = g_ij (T_i - T_j) = -q_ji`; conductance has units W/K. Contact
resistance in m² K/W must be divided by contact area to obtain K/W. Sidewalls
without an explicit contact remain insulated; empty space is not silicon.

The assembled model obeys `G theta = P`, `theta = T - T_ambient`, and
`G 1 = sink`. With reciprocal, nonnegative edge conductances and a positive
sink in every connected component,

`xᵀ G x = Σ_edges g_ij (x_i-x_j)² + Σ_nodes sink_i x_i² > 0` for nonzero x.

This gives the mathematical basis for a unique passive steady solution.
The audit checks the corresponding matrix properties within floating-point
tolerance, local balance, total input/removed power, and the maximum principle
for nonnegative heat sources. A separate hand-solved two-node test supplies
known energy and entropy values; negative-conductance, asymmetric, leaking and
unanchored controls must fail.

Use **kelvin** for entropy. Internal conduction/contact entropy production is
`Σ g_ij (T_i-T_j)²/(T_i T_j)`; each boundary produces
`q_out (1/T_ambient - 1/T_i)`. These must be nonnegative. This ledger covers the
modeled heat-transfer network, not the electronic process producing the heat.
Its nonnegative entropy production follows structurally from the chosen passive
network; it is a necessary implementation check, not independent calibration.

Passing these checks does not identify the real package stack, conductivity,
TIM/contact quality, convection, or workload power. Constant material properties
and fixed power do not describe temperature-dependent leakage or thermal
runaway. Cell-center temperatures are not measured junction temperatures. A
result at 285 C from an assumed stack is not a qualified operating point.
No transient thermal claims are made without heat capacity and time integration.

## Electrical system and timing boundary

Start with charge/current continuity and an energy ledger that includes every
supply, stimulus port, stored electric/magnetic energy, heat loss and port energy
flow. Positive passive R/L/C elements cannot create energy. Active pad circuits
draw energy from their supplies; a negative instantaneous port power or signal
overshoot alone is not a conservation violation. Conversely, SPICE completing
does not certify the physical completeness or charge conservation of every
compact model. Full pad charge/energy validation remains outstanding.

For the channel, declare conductor and return paths, bump/pad reference planes,
per-unit-length R/L/G/C and their frequency domain. The existing RC ladder is
a declared approximation. A causal passive RC calculation is not proof that
magnetic energy, propagation, coupling or skin effects are negligible.

As a scale check **under the same ideal parallel-plate geometry already used
for C**, `C'=epsilon*w/h`, `L'_external=mu*h/w`, and `t_flight=l*sqrt(L'C')`.
For the current 3 mm, 10 um wide, 1 um plane spacing, nonmagnetic eps_r=3.9
assumption, this gives about 0.377 nH and 19.76 ps. These are not field-extracted
values or an added constant delay. `omega L/R` is frequency-dependent; no RC
admission threshold is inferred from one frequency. Flight time is not the
50% threshold delay measured with a finite input transition.

The distributed-line relations follow from Maxwell's equations; see the
[University of Texas transmission-line derivation](https://farside.ph.utexas.edu/teaching/em/lectures/node86.html).
The existing tool can support an independent RLC/line diagnostic using documented
[ngspice device models](https://ngspice.sourceforge.io/docs.html), but choosing
a simulator does not supply the missing geometry or calibration.

For a full lane, specify TX clock-to-Q, TX pad, channel, RX pad, capture clock,
setup/hold, rise/fall events, operating mode and supplies. A shared clock's
correlation and propagation must be represented once. A Ceff at an STA query
is not itself a measured external load or a complete distributed channel.
Receiver thresholds and input waveform shape must match the selected library
arc. The timing oracle checks this event bookkeeping; it does not qualify PHYs.

## Current decision and next scientific question

Keep original characterization stimulus, extracted netlist/PEX, load definition
and model revision as explicit unresolved dependencies. Upstream circuit fixes
may be tested as declared counterfactuals; do not mix revisions silently or fit
parameters to force agreement. The current controlled SKY revision experiments
do not constitute a complete PDK upgrade.

The immediate scientific question is **when the declared reduced channel model
preserves the timing-feasibility decision**, at a fixed interface and physical
geometry. First compare RC and independently solved passive RLC/distributed
models with the same reference planes, stimuli and receiver; inspect energy,
waveforms, thresholds, setup and hold. Establish a prespecified decision
tolerance tied to the intended interface, not to the results we happen to get.
Treat an ideal-geometry mechanism case separately from a sourced hardware case.

Only after these boundaries are established should placement experiments test
whether satisfying a justified timing requirement changes the best achievable
temperature. A faster optimization algorithm cannot repair a wrong constraint.
Existing zero-penalty controls remain valid conditional results; no optimizer
or hot-pad model is admitted by this milestone.
