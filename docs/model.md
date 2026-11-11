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
No RC delay, SPEF, setup, hold, WNS or TNS is produced.

## Evidence

Provenance text is required for power, thermal and interconnect parameters;
it is attribution, not an automatic verification of their accuracy. The
report preserves those strings, the normalized input hash, source revision
when available, runtime versions and UTC evaluation time. Git dirty state is
recorded; it does not capture a full patch, so use a clean committed checkout
for reproducible comparisons. A separate runtime directory is required for
each evaluation. Repository-relative example files contain synthetic data only.
