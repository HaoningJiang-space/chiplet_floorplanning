# Input and model contract (schema version 1)

`examples/two_chiplets.json` is the complete executable input example. All fields
are required; unknown fields are rejected. IDs match `[A-Za-z][A-Za-z0-9_]*`.
Numbers must be finite. Lengths in JSON are **mm**, power is **W**, temperatures
are **degrees Celsius**, conductivity is **W/(m K)** and sink coefficient is
**W/(m² K)**. Thermal equations convert mm to m explicitly.

## Geometry and power

The package origin is its lower-left corner. Chiplet dimensions refer to its
unrotated local frame. Rotation is counterclockwise. `placement_mm` specifies
the **lower-left corner of the rotated bounding box**, not the rotation centre.
For local point `(u,v)` in a `w × h` chiplet, before placement translation:

| Rotation | Transformed point |
| --- | --- |
| 0 | `(u,v)` |
| 90 | `(h-v,u)` |
| 180 | `(w-u,h-v)` |
| 270 | `(v,w-u)` |

Blocks and ports use the same transform. Touching chiplets/blocks are legal;
positive-area overlap is rejected. Ports can lie on the boundary. Blocks need
not cover an entire die: uncovered area has zero declared heat input. Every
block must have an explicit total `power_w` and nonempty `provenance`; zero is
allowed but never inferred for a missing block. Dynamic and leakage components
should be summed upstream into that total, without double-counting I/O energy.

Power is uniform inside a block. For thermal cell g and block b:

`P[g] = sum_b P[b] * area(g intersect b) / area(b)`.

There is no renormalization to conceal clipping. Every block must be inside
its chiplet, and each chiplet inside the package. Each block's mapped power
must equal its input within `rtol=1e-10`, `atol=1e-12 W`.

## Thermal reference

`uniform_slab_steady` assumes one uniform thin slab of conductivity k and
thickness t, adiabatic lateral boundaries, and distributed heat removal h to
a single ambient. It solves the cell-centred finite-volume system:

`sum_j G_ij (T_i - T_j) + h A_i (T_i - T_ambient) = P_i`.

On a uniform rectangular mesh:

- horizontal conductance: `Gx = k t dy / dx`;
- vertical conductance: `Gy = k t dx / dy`;
- sink conductance: `Gs = h dx dy`.

The solver solves for temperature rise, with no ghost coupling across the
insulated package boundary. A strictly positive h makes the system anchored.
Its residual and total heat removal are checked against `1e-8 * max(1, Ptotal)` W.
These numerical checks do not demonstrate that the boundary conditions or
material parameters represent a real package.

The slab remains the same when a chiplet moves; only heat sources move. There
is no die-specific thickness, underfill, interposer, heatsink stack, transient
capacity, thermal feedback to power, or thermal timing in this version.

## Interconnect and timing

Links connect named ports on different chiplets. Data and clock are explicit
independent entries. Their length is `abs(dx) + abs(dy)`. The reported R and C
are length multiplied by explicit input coefficients in ohm/mm and pF/mm.
They omit all pad, bump, receiver, coupling, inductance and routing effects.
The original `manhattan_lower_bound` mode alone produces no delay or slack.
The optional lane harness described below adds SPEF and real STA.

## Evidence

Provenance text is required for power, thermal and interconnect parameters;
it is attribution, not an automatic verification of their accuracy. The
report preserves those strings, the normalized input hash, source revision
when available, runtime versions and UTC evaluation time. Git dirty state is
recorded; it does not capture a full patch, so use a clean committed checkout
for reproducible comparisons. A separate runtime directory is required for
each evaluation. Repository-relative example files contain synthetic data only.

## v0.2 layered package

`layered_package_steady` replaces the slab parameters with ordered bottom-to-top
`layers` (id, footprint, thickness_mm, conductivity_w_mk), `power_layer`,
`top_h_w_m2k`, `bottom_h_w_m2k`, ambient and provenance. A layer footprint is
either the entire package or the union of chiplet rectangles. Die edges must
align to the uniform thermal grid; unsupported partial material cells fail.
Gaps in chiplet-only layers are void, with no artificial material or heat source.
All lateral/exposed internal surfaces are adiabatic. Radiation, underfill,
contact resistance and anisotropy are not represented in this version.

Neighbour conductance within a layer is `k t A_edge / distance`; across adjacent
layers it is `A / (t1/(2*k1) + t2/(2*k2))`. Surface convection uses
`A / (t/(2*k) + 1/h)`; h=0 means insulated. The report contains all solid-node
temperatures and `(layer,y,x)` indices. The main grid temperature is the source
layer temperature; CSV temperature is blank where that layer is void, never
an invented ambient-temperature material node. Summary means cover active
source-layer cells only.

## v0.2 electrical model

`rectangular_wire_parallel_plate` accepts `resistivity_ohm_m`, `width_um`,
`thickness_um`, `dielectric_height_um`, and `relative_permittivity`. With the
Manhattan length L, it evaluates `R=rho*L/(w*t)` and `C=epsilon0*epsilon_r*w*L/h`.
This ideal grounded parallel-plate approximation omits fringing, coupling,
frequency dependence, inductance, bumps and real routing obstacles. It is a
specified model to validate, not an extraction from a foundry package kit.

The optional fixed lane requires `tx` and `rx` chiplets and ports `data` and
`clock`. SKY130 HD launches through a characterized buf_8; GF180 MCU7T5V0
receives through a DFF and an inverter on the forwarded clock. A generated
inverted capture clock provides the opposite-edge sample. Timing is explicitly
TT, 25 C, 1.8 V; min/hold uses the same TT library, not a certified fast corner.
Both package nets receive an eight-segment RC network. SPEF contains wire
capacitance only; Liberty supplies input pin capacitance exactly once.
Internal wires use a generated zero wire-load model; no automatic library
wire-load estimate is silently applied. Data and clock wire capacitance are
read back from OpenSTA and checked against the generated networks.

SKY130 uses 20–80% slew thresholds; the selected GF180 **core** library uses
30–70% with `slew_derate_from_library=0.5`. This differs from the I/O-library
thresholds discussed in initial planning. OpenSTA's pinned
`LumpedCapDelayCalc::thresholdAdjust` applies the cross-library convention
conversion. Raw library slew numbers are not treated as the same measured
transition interval. Metadata and original library hashes are retained.
