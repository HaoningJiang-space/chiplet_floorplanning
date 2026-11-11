# Validation gates and implementation roadmap

## G0 — Input and numerical foundation (v0.1.0)

Fixed layout, rotation-aware geometry, explicit block power, conservative
mapping, and a uniform-slab steady reference. Analytic solution tests establish
numerical consistency for this limited equation. G0 does not establish physical
package accuracy, workload power accuracy or timing feasibility.

## G1 — Reference package thermal integration (numerical comparison complete)

v0.2 implements a five-layer package with chiplet islands and has passed the
predeclared MFIT network comparison, conservation, analytic and mesh checks.
The comparison executes MFIT's unchanged Python network methods and solves
its steady matrix with NumPy; it does not execute the native transient binary.
Measured package calibration and POSTsim integration remain pending.

Inspect the actual POSTsim API and existing package/material inputs. Add an
adapter once its input/output contract is known. Pin an independent MFIT or
3D-ICE version and reproduce a published/repository case. Match geometry,
materials, sinks, mesh and power before comparing the solvers. Record
pointwise/peak-temperature errors and mesh refinement results; tolerances must
be chosen from the intended layout-decision resolution, not after seeing results.

Keep assumed power as a labelled control. Separately introduce sourced workload
block traces or RTL/Liberty/activity-derived power. Missing SRAM/PHY models must
remain missing evidence, not implicit zero power. Power traces need explicit
window duration and dynamic/leakage accounting before transient work begins.

## G2 — Room-temperature cross-die timing (core-cell harness complete)

v0.2 integrates SKY130 HD → GF180 MCU7T5V0 at TT/25 C/1.8 V with real
Liberty, explicit data/forwarded-clock SPEF, expanded setup/hold paths,
electrical limit checks, sensitivity controls and passive RC SPICE comparison.
Pad/ESD/PHY models, extracted package channels, transistor-level driver
comparison, full PVT coverage and hardware signoff remain pending. The original
full-interface gate below is therefore not claimed complete.

Use two dies, one data path and one forwarded-clock path. First inventory
available netlists, compatible pad models, PDK models and OpenSTA version.
Verify levels, thresholds, slew definitions and loads before selecting the
heterogeneous PDK pair. SKY130/GF180 is a candidate, not a validated choice.

Add an explicit route/segment model, separate pad/bump/wire ownership and SPEF
export. Build a top-level netlist and generated-clock/edge constraints. Require
complete setup and hold reports, both clock and data parasitics annotated,
no unexplained black boxes or unconstrained endpoints, and representative
waveform/circuit-simulation agreement. No replacement of setup/hold with a
distance-based score is permitted. Freeze the base design before length sweeps.

## G3 — Local temperature to timing (software integration, physical validation pending)

v0.3 adds a pinned FF core-cell profile, rotation-aware instance temperatures,
table interpolation, per-instance libraries and setup/hold recomputation.
Cold/hot endpoint equivalence and independent original-table queries pass.
Intermediate-temperature accuracy still needs independent characterization;
the real TT GPIO lane is rejected for receive-pad slew exceeding its limit.
See `validation-v03.md` for the exact PVT matrix and retained negative results.

Characterize or obtain temperature models at fixed process and voltage. Validate
instance-to-temperature mapping, library linking, data/clock paths and receiver
constraints. Include temperature points not used in fitting. Do not change only
nominal Liberty temperature metadata and interpret it as characterization.

## G4 — Floorplanning search (pending)

First show a reproducible layout-ordering change larger than model error. Use
wirelength-only and thermal-only controls, an identical final evaluator,
identical workload/frequency/constraints, and repeated seeds. Report legal and
timing-feasible fractions, worst setup/hold margin, peak temperature, routed
length and runtime. Preserve negative results if thermal timing does not alter
the decision. Do not attribute an improvement to coupling without this control.

## Git workflow

Maintain only `main`, both locally and on `origin`. Commit validated changes
directly on `main`; remove development branches once fully merged.
Commit source, tests, synthetic examples and compact validation receipts. The
latest user direction is local experiments only: fetch for freshness, but do not
push or trigger remote CI unless publication is subsequently requested. Exclude raw experiment outputs, environments,
credentials, private host configuration and restricted third-party models.
Public visibility is intentional; it does not itself select a software license.
A redistribution license for original project code is not yet selected.

## v0.4 update — geometry and low-speed interface

Conformal nonuniform XY geometry, explicit contact resistance/anisotropy,
die-restricted continuous temperature sampling and declared rectilinear route
lengths are implemented. Moving a die preserves its coordinates and invalidates
stale explicit routes. Instance-temperature and slack refinement checks now
complement peak-temperature checks.

The GF180 TX -> SKY130 RX TT GPIO prototype passes the declared software gates;
the original opposite direction is a retained slew failure. Pad modes, voltage
domains, actual receiver buffers and source-table domain checks are explicit.
This advances G2 without completing its transistor-waveform/physical gate.
The core-only local-temperature profile remains separate from this pad lane.
See `validation-v04.md` for passing cases, failures and remaining evidence.

## v0.5 update — open cases and ranking gate

Independent-die sidewalls, per-die conductivity on a common stack, offset layer
rectangles and parameterized placements are implemented. Three public MFIT
physical-input cases pass matched-network and XY refinement gates; RapidChiplet
provides a 16-die geometric conversion control. PULP's unchanged SDR PHY passes
bounded transport cases and a late-data negative control. These checks have
separate evidence scopes and do not establish physical signoff.

The predeclared 27-candidate experiment yields 20 electrically legal TT lanes
and 7 retained electrical failures. Independent data/clock detours reveal
opposing setup/hold responses; common delay largely cancels in setup. Thermal
and TT timing objective conflicts are numerically resolved, but temperature
is not applied to these pads. G4 remains gated on consistent interface
characterization and physical/model error, not merely a different score winner.

## v0.6 update — transistor-model gate remains closed

The identical GF180 TX / SKY130 RX logical modes now have hash-locked transistor
decks, source hierarchy/conversion audits, independent waveform measurements,
half-step checks and a conditional fixed-TT/P/V GF180 temperature sweep. Nominal
Liberty disagreement, reachable empty SKY130 subcircuits and simulator model
warnings remain explicit failures. No synthetic hot-pad Liberty is produced.
The next dependency is a complete, traceable pad netlist/model/characterization
setup that reconciles nominal delay and slew, including its load convention.
Temperature holdout consistency alone does not resolve that missing baseline.
See `validation-v06.md`. G3's full-interface gate and G4 remain open work.

## v0.7 update — route policy and constraint necessity

The fixed 27 placements now have a declared single-layer finite-width geometry
gate, an obstacle-aware paired-path heuristic and a finite joint route portfolio.
R2 reproduces the prior 121 conflicts locally (115 on the CI build, with exact
agreement between old/new runners there). R1/R4 preserve timing feasibility for all
27 and reduce the full setup spread to 0.007 ps under the same fixed TT model.
R3's exchanged corridors short on this layer and are rejected before STA.
All populated policies select layout 26 for minimum temperature subject to
timing; the timing constraint thermal penalty is zero. These are conditional
model results, not physical-error-qualified predictions.

The next question is when a justified requirement makes the thermal optimum
infeasible, not how to reward extra positive slack. A pinned Basilisk SDC audit
provides an admission reference, but no real timing-critical benchmark has yet
been implemented. Keep G4 pending and do not add SA on the strength of weighted
scores. See `timing-benchmark-admission.md` and `validation-v07.md`.

P1 remains: measure legal-range SPICE/Liberty differential sensitivity without
offset fitting, and reconcile the same-interface nominal model before enabling
hot-pad timing. Only then measure S_T(X)-S_0(X) and the pair interaction
[S_T(B)-S_T(A)]-[S_0(B)-S_0(A)]. The fields are currently null.

Per-evaluation timing is now recorded. A route comparison may reuse thermal
results only for the identical placement, power, stack and mesh. Different
placements still rebuild their matrices. Consider caching or a persistent STA
engine only after profiling on the future admitted design; do not assume equal
matrices or a transferable acceleration from this small case.

## v0.8 update — thermal locality before optimization

E1 now independently solves total/TX/RX heating while retaining all materials.
All power-only changes preserve the matrix, sink and material-node identities.
The 27 nominal layouts reproduce v0.5, and six boundary/TIM profiles pass the
declared final XY mesh-change screen after refining the entire bottom-cooled
profile. Rigid translation mainly changes the TX contribution at the total
hotspot; RX's absolute contribution is still about 10 K. A conditional 20/26
rank reversal under lower TIM conductivity demonstrates sensitivity to the
assumed stack, not a universal optimal placement. See `validation-v08.md`.

Keep the scope at timing-driven physical feasibility. E2 next requires a sourced
pin/bump order, shared-clock timing group, finite signal-layer resources and
keepouts. A cut-capacity upper bound below mandatory demand can certify
infeasibility **only within that declared resource model**; sufficient capacity
or failure of a routing heuristic cannot certify routability/infeasibility.
Do not narrow a channel merely to create the desired effect. Existing two-wire
geometry is not a general resource graph or a qualified multilane benchmark.

E3 must use the same admitted interface, PDK, operating mode and sourced edge
requirements. Compare the best temperature among geometry/electrical-legal
placement–routing pairs with that among timing-feasible pairs. A finite search
only provides a result for the enumerated set; it cannot prove that every legal
route at a placement is infeasible. Retain v0.7's zero-penalty control. Even a
positive constraint penalty would not establish superiority of joint search
over sequential/alternating methods at equal budgets. E2/E3 and G4 remain open.

## Local semantic-oracle milestone (2026-11-11)

Native Windows now reproduces the upstream STA goldens, TT GPIO prototype and
v0.8 E1. A separate synthetic event oracle checks all four rise/fall setup/hold
paths, actual clock transitions, fixed event pairing, data/clock/common delay
controls, explicit early/late corners and eight malformed-contract controls.
See `timing-oracle-contract.md` and `windows-local.md`. No physical-calibration
or optimizer gate is closed by this milestone.

The real-library contract bridge is now locally checked on two circuit families
with 42 parameter cases and all four setup/hold rise/fall paths; see
`local-multicase-results.md`. This is source-table/contract consistency, not an
independent physical propagation oracle. Next diagnose the pad-model mismatch,
retaining every electrical/table-domain gate. Admit a sourced resource
case or clearly label a synthetic mechanism case, and set decision tolerances
before testing whether routing can eliminate the thermal/timing conflict.

## Source provenance and physical invariants (2026-11-11)

The next local milestone traces the pad netlist/Liberty lineage and tests
source-supported SKY IO corrections in isolated copies. It also checks necessary
conservation/passivity/entropy properties of four declared thermal cases and
exposes the electromagnetic scale omitted by the current RC channel. See
`pad-provenance-results.md` and `physical-admission-contract.md`.

Recovering file lineage is not recovering the original characterization/PEX
contract. Keep the nominal mismatch, empty primitive definitions, model warnings
and uncalibrated stack explicit. Neither table agreement nor the thermal network's
structural entropy property is independent hardware validation.

Before further optimization, compare a declared same-geometry RC/RLC mechanism
case with fixed return path, waveform, driver, receiver and reference planes.
Use charge/energy ledgers and compare both setup and hold at prespecified
decision tolerances. Do not infer RC failure from a single frequency or add an
ideal flight-time constant to STA. A sourced hardware case still requires
independent material/channel/interface evidence.
