# Goal 01: timing-feasible electrothermal floorplanning

This goal supersedes the previous ten-metric work sequence. The question is
whether actual routing and setup/hold exclude the thermal minimum, and whether
temperature feedback changes that conclusion. Zero cost is an admissible result.
Do not tighten frequency until a desired conflict appears. TTC refinement stays
background evidence, not a prerequisite to the integrated decision benchmark.

## First integrated contract

`chiplet_floorplanning.floorplanning.evaluate(layout, configuration)` connects
one fixed design to rotated local pins, finite routing resources, a layered
thermal field, unique conductor SPEF, and every lane's full propagated-clock
setup/hold report. The first design has one TX, two RX and four lanes per RX.
`examples/three_chiplet_decision.json` fixes all inputs; geometry changes do not
retain old routes. Data, clock, VDD and VSS landings all rotate. Power and signal
bump columns reserve routing resources. Interposer routing below dies is allowed.
Power pins are geometrical reservations on ideal supplies, not a PDN/IR analysis.

All active core cells use the same pinned SKY130 HD TT process and 1.8 V, with
public 25/100 C tables. Buffer, positive-edge FF and inverter cells implement a
shared root, TX bank, forwarded clock, RX branch and opposite-edge capture.
The reference run uses 25 C for cells and wire; the feedback run uses local die
and interposer temperatures. Each data/clock arc's load/slew and RX setup/hold
table lookup is independently checked inside the table domain. Common clock
paths are present in the netlist, not added as an independent penalty.

This is a **core-boundary mechanism study**, not an actual Pad-qualified D2D
interface. Pin coordinates are explicit designed landings, not coordinates
recovered from a manufactured pad ring. Pad/ESD/bump transfer functions, internal
die routing, return/coupling/inductance effects, jitter, PVT variation and measured
channel validation remain absent. The period is fixed at 20 ns; this is a study
condition, not a maximum-frequency qualification. The previous GF/SKY Pad
SPICE/Liberty mismatch is unresolved and is not repaired by using core tables.

## Coupling and conservation

The package uses positive reciprocal finite-volume thermal conductances with
fixed workload power and fixed ambient. Energy balance is checked. The separate
TTC measurements do not calibrate this assumed package. Device temperatures use
die-restricted interpolation; both thin signal layers follow the modeled
interposer layer temperature. This thickness approximation, boundary clamping,
and linear 25/100 C core-table interpolation require further verification.

Each conductor appears once in SPEF, including the multicast clock trunk. Wire
and via capacitance belong to SPEF; receiver capacitance belongs to Liberty,
including separate rise/fall values. Positive resistance and capacitance give
a passive RC model. Independent nodal and tree first moments agree. OpenSTA's
`simple_rc` is a one-pole approximation, not a distributed waveform reference.

The declared copper model uses `R(T)=R20[1+alpha20(T-20)]`, `alpha20=0.00393/K`
and standard annealed copper resistivity from
[NBS Handbook 100](https://nvlpubs.nist.gov/nistpubs/Legacy/hb/nbshandbook100.pdf).
Applying bulk wire data to assumed fixed thin-film geometry is a mechanism
assumption, not metal extraction or temperature calibration. Geometry, C and
via reference parameters remain explicit assumptions. No route-dependent
dynamic loss or temperature-dependent leakage power is added to the fixed I/O
block budget. Consequently this model is one-way temperature feedback, not a
self-consistent power/temperature iteration.

The backend uses the documented
[OpenSTA clock, SPEF and report commands](https://opensta.readthedocs.io/en/latest/Commands/).
The root input transition is explicitly assigned to the physical clock port:
`set_clock_transition` alone does not set a propagated clock's input slew.
No ideal zero-slew root is accepted as an in-domain library operating point.

## Run locally

```powershell
. ./tools/windows_env.ps1
python tools/evaluate_floorplan.py examples/three_chiplet_decision.json --output results/decision-example
```

Inputs, exact placed geometry, route trees, thermal arrays, local temperature
assignments, per-instance libraries, SPEF, STA logs, all path values and hashes
are saved. Raw assets remain ignored locally. `status=analyzed` means this
declared model was evaluated; physical signoff remains false. Greedy search
failure is unknown; a verified full-cut capacity certificate is needed for a
declared-fabric infeasibility claim. Electrical rejection and missing/model-domain
evidence are distinct from a valid negative setup/hold slack.

Initial smoke case: 3 W, peak 67.299850855 C; reference worst setup/hold
9.803927422/10.013956070 ns; feedback 9.813965797/10.019234657 ns. Both pass.
All 32 path checks in each run passed; 1,088 bounded table/reference checks had
maximum error 2.03e-6 ns. This numerical agreement does not establish SPICE
waveform accuracy, interpolation accuracy, or the physical optimum.

## Finite benchmark and proof obligation

Freeze a finite placement/rotation domain and the package/interface/workload
before observing outcomes. Enumerate placements, evaluate declared route
policies, and retain unknown routing outcomes. Thermal minima over all legal
placements give a lower bound because power is route independent in this model.
A legal, admitted, timing-feasible route gives an upper bound. If a thermally
minimal placement has such a route, the bounds coincide and certify the optimum
over *all* declared-fabric routes for that finite placement set, despite an
incomplete router. Otherwise report an interval; missing routes cannot certify
positive temperature cost or global infeasibility.

Report geometric thermal, routed thermal, electrical admission, constant-T
timing and feedback timing subsets separately. Use paired mesh refinement on
the best and nearby candidates to judge ranking stability, and preserve ties
or unresolved differences. Baselines share the exact evaluator/domain/budget;
full-budget equality is a control, not an algorithmic superiority claim.

Next physical gate: matched SPICE/STA data/clock differential delay and slew at
the same reference planes, followed by a physically characterized Pad/channel
backend. A numerical core mechanism result cannot substitute for that gate.
