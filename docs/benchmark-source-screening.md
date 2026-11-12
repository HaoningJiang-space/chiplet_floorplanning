# Initial source screening, 2026-11-12

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
or measured workload traces. The README calls the matrix bandwidth but does not
give a unit there. `compute_ubump_overhead` sums incident demands and divides
ring area by a 0.045 mm pitch squared, with a factor of two for pipelined links.
This implies a conversion assumption that must be checked against the paper
before interpreting matrix entries as physical wires or bandwidth.

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
