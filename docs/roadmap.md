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

Use `main` for tested milestones; develop larger changes on topic branches.
Commit source, tests, synthetic examples and compact validation receipts. Push
each validated milestone. Exclude raw experiment outputs, environments,
credentials, private host configuration and restricted third-party models.
Public visibility is intentional; it does not itself select a software license.
A redistribution license for original project code is not yet selected.
