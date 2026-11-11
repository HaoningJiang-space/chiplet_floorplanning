# Input and model contract (schema version 1)

`examples/two_chiplets.json` is the complete executable input example. All fields
are required unless explicitly documented as optional; unknown fields are rejected. IDs match `[A-Za-z][A-Za-z0-9_]*`.
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
is no die-specific thickness, underfill, interposer or heatsink stack in this
slab model. Transient capacity and thermal feedback to power are not modeled.

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

## v0.4 geometry and thermal interfaces

For a layered case, `grid.mode` defaults to `geometry_conformal`; the slab
retains `uniform` by default. `nx,ny` specify the target maximum cell pitch,
not a guaranteed final count in conformal mode. Package, die and power-block
edges partition each axis; each interval is subdivided to that target pitch.
The input geometry is preserved. Distinct edges below floating-point resolution
are rejected. The output records requested/actual counts and exact mesh edges;
CSV includes each cell's width and height. Explicit `uniform` mode still rejects
nonaligned layered material boundaries, serving as a regression control.

For neighbours with different widths, face conductance is
`kx * thickness * face_height / ((width_i + width_j)/2)` (and analogously y).
Each layer accepts exactly one of `conductivity_w_mk` or
`conductivity_xyz_w_mk: [kx, ky, kz]`, with positive components. Optional
`contact_resistance_above_m2k_w` is a nonnegative area-normalized contact
resistance. Across layers, use
`G = area / (t1/(2*kz1) + contact_R + t2/(2*kz2))`.
A positive contact resistance above the final layer is rejected. Surface
half-cell conduction and convection are in series. Heat removal and reported
mean temperature use actual cell area, not equal weights on nonuniform cells.

The material representation remains axis-aligned rectangular islands at quarter
rotations, a common layer stack and one temperature node per physical layer in z.
Different die thicknesses, polygons, tilted dies, resolved bump arrays and
arbitrary 3D CAD are outside this representation. The source layer centre
is an explicitly approximate temperature location, not a measured junction.

Instance temperature is bilinearly reconstructed from cell centres **inside
that instance's die only**, with clamping at its centre-range boundary.
Weights, source indices, local/package coordinates and clamping flags are
recorded. No interpolation crosses to another die or a void. Boundary clamping
needs mesh convergence; no new physical temperature data are implied.

## v0.4 explicit package routes and pad contract

A link optionally supplies `route_points_mm: [[x0,y0], ..., [xn,yn]]` in package
coordinates. Every segment must be nonzero and axis aligned; points must lie
inside the package. First/last points must match transformed source/target
ports. A die move invalidates a stale route and requires rerouting. RC uses
the sum of segment lengths; `manhattan_length_mm` remains the geometric lower
bound, while `modeled_length_mm` is the actual declared length. These are ideal
constant-section conductors without bend discontinuities, routing DRC or
coupling. The eight-section SPEF distributes the total RC over electrical length.

`--pad-direction gf180_to_sky130` selects the fixed mode in `interfaces.py`:
GF180 bi_t (OE=1, IE=0, PDRV1:0=11, SL=0, pulls off) to SKY gpiov2
(DM=001, OE_N=1, INP_DIS=0, CMOS input), then real buf_16/inv_8 receiver cells.
The [GF control table](https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html)
and [SKY mode table](https://skywater-pdk.readthedocs.io/en/main/contents/libraries/sky130_fd_io/docs/user_guide.html)
are the mode sources. Both I/O supply domains are 3.3 V; the SKY input's IN pin
interfaces to its 1.8 V core. Physical supplies, power sequencing, pad ring,
DC noise margin and ESD implementation are not validated by this logical netlist.

Pad capacitances belong to Liberty. SPEF contains only the declared wire C;
no extra pad capacitance is added. Actual GF timing-table load axes already
include its pad self-capacitance and are used unchanged. Active pad timing
checks independently interpolate original source tables at STA's input slew
and Ceff for all four pads, rise/fall and min/max. Out-of-domain queries fail.
The checker covers these pad tables, not all core setup/hold table domains.

OpenSTA 2.2's capacitance report uses float arithmetic. Wire C readback permits
four float32 relative epsilons of the reported total C to bound cancellation
against much larger pin capacitance. Zero annotations and requested wire C
below this reporting resolution are rejected. No electrical limits are relaxed.

## v0.5 independent die boundaries and placement API

The ownership of each material cell is retained in chiplet-only layers. Adjacent
cells belonging to **different dies have no lateral edge by default**, including
zero-gap contact. Shared `package` or `rectangle` layers conduct continuously.
An absent sidewall model means adiabatic, not fused silicon and not an estimate
of real underfill conductance.

Optional layer fields:

```json
{
  "id": "dies", "footprint": "chiplets", "thickness_mm": 0.1,
  "conductivity_w_mk": 150,
  "die_materials": {"rx": {"conductivity_xyz_w_mk": [120, 120, 100]}},
  "sidewall_contacts": [{"dies": ["tx", "rx"], "resistance_m2k_w": 0.0001}]
}
```

A contact requires geometrically touching edges with positive overlap; it cannot
bridge a gap or corner. Unordered duplicate pairs are rejected. Both conductivity
forms must be positive; xyz components always refer to **package axes**, not a
rotated crystal tensor. For a face of area A normal to x,
`G = A / (dx_i/(2*kx_i) + contact_R + dx_j/(2*kx_j))` (analogous in y).
The explicit R=0 contact gives ideal intimate contact with the two material
half-cell resistances. Per-die assignments apply only to chiplet footprints.
Thickness remains common within each layer; vertical contact resistance is
still a layer-wide scalar. This is not an arbitrary heterogeneous 3D stack.

`footprint: "rectangle"` requires `rect_mm: {x,y,width,height}` within the package.
Its boundaries enter the conformal mesh. This supports offset interposer/C4
footprints; exposed surfaces remain insulated unless they are the declared
outermost top/bottom convection surface. No automatic material fills a gap.

```python
from chiplet_floorplanning.model import load_case
from chiplet_floorplanning.layout import place_design, evaluate_layout
base = load_case("examples/low_speed_gpio.json")
candidate = place_design(
    base, {"tx": {"x": 1.5, "y": 3.0}, "rx": {"x": 7.0, "y": 2.0}},
    corridors_y_mm={"lane_data": 1.5, "lane_clock": 4.5},
    grid={"nx": 96, "ny": 64, "mode": "geometry_conformal"},
)
result = evaluate_layout(candidate)
```

The base design, power, material and electrical parameters are not mutated.
Moved endpoints are transformed and both routes rebuilt before validation.
A corridor is an ideal rectilinear connection, not a legal routed implementation;
STA uses its total RC, not position-dependent wire temperature. Spatial pad
characterization, channel extraction and physical uncertainty remain missing.

## v0.7 declared planar routing domain

`PlanarRules` keeps geometry rules separate from the thermal/electrical input.
Rules contain positive `trace_width_um`, `spacing_um`, `edge_clearance_um`,
explicit rectangular `keepouts_mm` and provenance. The width must agree with
the case's electrical width when that field is present. The reference uses
10 um for each rule as an assumption, not an imported foundry rule deck.

Traces occupy a single interposer signal layer below the dies. No die footprint
becomes a keepout implicitly. The trace is a union of axis-aligned rectangular
segment envelopes, each expanded by half the width, including square endcaps.
For the reference planar checker:

- centerlines stay at least half-width plus edge clearance inside the package;
- explicit keepouts expand by half-width plus spacing;
- different traces require at least width plus spacing between centerlines;
- repeated vertices, backtracking and nonadjacent self-clearance violations fail.

Distances use the L-infinity metric, a conservative square clearance near
corners. Endpoints are validated against the rotated die ports by `parse_case`.
The model does not describe bump landing shapes, escape routing, metal density,
vias, crossovers or coupling. Passing this contract is not physical package DRC.

`shortest_route_pairs` supports exactly two nets, tries both routing orders and
chooses the shortest legal pair it finds. Each net uses a rectilinear visibility
grid of package bounds, expanded obstacle bounds and terminal coordinates;
Dijkstra minimizes length, breaking ties by bends. Other-net terminals and
already placed conductors are obstacles. This heuristic may miss a feasible
joint route and does not certify globally optimal routing. For the 27 reference
placements only, the returned legal pair reaches the sum of independently
computed Manhattan lower bounds, which does certify its length for that case.

Thermal reuse is valid only across routes of the same placement/power/stack/mesh
in this model, which omits wire heat and metal-pattern conductivity. A change of
placement rebuilds the conformal mesh and thermal matrix. Optional `timings_s`
dictionaries record construction, assembly and solve wall times without changing
the equations. STA still launches an external process for every unique route.

The v0.7 evaluator minimizes temperature **subject to** nonnegative setup/hold
and geometry/electrical legality. It first identifies the thermal optimum before
filtering timing; filtering first would hide a timing-infeasible thermal optimum.
Pareto sets and opposing score rankings are reported separately from necessity.
The current same-interface temperature-dependent result S_T and pair interaction
are missing, never zero-filled. All pad results remain fixed TT25 with the v0.6
nominal-model discrepancy unresolved.
