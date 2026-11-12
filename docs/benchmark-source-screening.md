# Initial source screening, 2026-11-12

Follow-up: the [IHP attachment admission audit](ihp-attachment-admission.md)
checks a compatible pinned public ADK/PDK bundle and proves why its standard
attachment methods cannot be applied unchanged to the frozen TAP bump sites.

This is provenance screening, not a frozen benchmark or physical qualification.
Read-only source clones are stored under ignored `local/upstream/`. No external
tool was executed and no remote experiment was launched.

## TAP-2.5D

Pinned upstream: `bu-icsg/TAP-2.5D`,
`3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb`.
[Primary repository](https://github.com/bu-icsg/TAP-2.5D/tree/3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb).
The README identifies three paper case studies, HotSpot 6.0 thermal evaluation,
and a CPLEX-based routing optimization baseline.

| Published configuration | Chiplets | Interposer side | Sum of configured powers |
|---|---:|---:|---:|
| `configs/sys_ascend910.cfg` | 6 | 50 mm | 350 W |
| `configs/sys_micro150.cfg` | 8 | 50 mm | 680 W |
| `configs/sys_multigpu.cfg` | 6 | 50 mm | 755 W |

The dimensions, powers and connection matrices are present in each configuration.
Treat them as published case-study inputs, not verified product specifications
or measured workload traces. The README calls the matrix bandwidth without a
unit. The paper's Table I, checked subsequently, defines R_ij and the flow
variables as wire counts in its routing abstraction. `compute_ubump_overhead`
sums incident demands and divides
ring area by a 0.045 mm pitch squared, with a factor of two for pipelined links.
This is consistent with aggregate wire-count demand. It does not specify
per-wire data rate, protocol overhead or a complete signal/clock/return bump map.
The Table I correction was made after a successful fetch with local/remote
`main=f718f77d5370fa95ab69b1b4181caf4818cd5558`. Reimporting all three cases
preserved their numeric inputs and direct-flow witnesses; only provenance and
the bound ledger hash changed. All 244 local tests and the documented 3 W
two-chiplet CLI passed (34.1886 C, uncalibrated, timing not run).

`passive_interposer.py` also contains package layer thicknesses, effective
material assumptions and heat-sink area scaling. Its comment explicitly leaves
central power/ground/clock bump density assumed. Preserve these assumptions;
do not describe this package as independently calibrated. Reusing dimensions
without its bump-overhead and cooling semantics would change the problem.

## RapidChiplet

Pinned upstream: `spcl/rapidchiplet`,
`17176f92c91eda629a25bc11bf7959d6b963a23b`.
[Primary repository](https://github.com/spcl/rapidchiplet/tree/17176f92c91eda629a25bc11bf7959d6b963a23b).
Inspected `experiments/example_experiment.json`, generated example chiplets,
packaging and technology inputs. These expose independent PHY coordinates,
topology/traffic settings and declared bump-area fractions. The example uses
synthetic technology labels and a link-latency function, so it is not a qualified
PHY or package timing model. It is a candidate source for scalable communication
families, not a direct replacement for track-capacity routing or thermal data.

## Next bounded sourcing decision

First check TAP's paper against its configuration units, port abstraction and
resource/cooling model. Select one coherent family for the first frozen domain.
Use RapidChiplet only if a separately labeled architecture-level extension is
needed; do not silently combine its PHY assumptions with TAP's thermal package
and claim a measured product. Freeze small exact and larger domains before
optimization experiments. Missing manufacturing details remain explicit
assumptions shared by all compared methods.

## Paper/code cross-check

The [authors' DATE 2021 paper](https://people.bu.edu/joshi/files/Ma_TAP-2.5D-DATE2021.pdf)
specifies four pin clumps per chiplet, aggregate pin capacity and Manhattan
distance (Section III-B). This is not an explicit routed-track congestion model.
It uses a 45 C ambient and fixed heat-transfer-coefficient convention, consistent
with the inspected config and area-scaled convection resistance. Its cases mix
conceptual systems and a commercial-system-inspired example; keep that distinction.

The code's `routing.py` catches solver exceptions and returns the numerical
penalty 100. An adapter must instead distinguish solver failure/timeout from
certified infeasibility, and must not treat that penalty as a feasible wirelength.
This is directly relevant to fair baseline comparison. Adopting finite track
resources would be a declared extension applied to every baseline, not a claim
that the published aggregate-pin formulation already models those tracks.

## Candidate interface reference: scope before numerical substitution

The [UCIe Consortium Hot Chips 2023 electrical tutorial](https://www.hc2023.hotchips.org/assets/program/tutorials/ucie/Electrical%20Form%20Factor%20and%20Compliance.pdf)
describes an advanced-package profile with 25–55 um bump pitch, up-to-2 mm
channel reach and x64 module width (PDF pages 2–3). It separately specifies
channel eye-mask and link timing ingredients (pages 10 and 13). Thus geometric
reach alone is not channel or timing qualification. The tutorial also notes that
reach can change with transmitter swing; 2 mm is a profile condition, not a
universal physical impossibility threshold.

This is a candidate specification reference, not permission to reinterpret TAP
HBM links or RapidChiplet's synthetic PHY as UCIe-compliant. A benchmark adopting
it must explicitly define compatible PHY modules, bump maps, channel geometry,
power and timing assumptions. It cannot certify the existing 1.8 V SKY130
core-boundary experiment or justify arbitrarily tightening its clock.
