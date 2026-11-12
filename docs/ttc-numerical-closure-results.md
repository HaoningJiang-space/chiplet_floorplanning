# TTC steady numerical closure

The original approximately 1.7 K discrepancy is now reduced to approximately
0.020 K without changing geometry, materials, physical boundary or power.
This closes the **frozen steady numerical screen** for the declared uniform-bath
stack. It does not validate the old coarse transient predictions or calibrate
the real package. The earlier spatial-improvement failure remains unchanged.

Implementation and frozen plan: `708fb42`. GitHub was fetched successfully;
origin remained `c124aa9`, with no incoming work. Experiments and commits stayed
local. Raw results: `results/physical-calibration/ttc-numerical-closure-v1/`.
Source code, protocol and dependency hashes were saved before predictions.
No measured temperature was used to choose grids or tune material properties.
The inherited fitted bath conductance only supplies a spatially common offset.

## First-principles calculation

Steady conservation is `G T = B P`. Each interior face transfers
`(T_i-T_j)/(dz_i/(2 k_i A)+dz_j/(2 k_j A))`; its equal and opposite contribution
appears in the neighboring cell. There is no storage term at steady state.
The insulated lateral boundaries have an exact constant mode. Its heat reaches
the uniform bath and then the ambient; the bath rise is `sum(P)/Ga`, added once.

For homogeneous layers with a shared lateral mesh, the finite-volume operator
separates. Mass-normalized one-dimensional modes obey `L v = lambda D v`.
Every lateral mode is retained, with a separate vertical tridiagonal solve.
This computes the same equations as a 3-D solve, without forming the large 3-D
matrix. Heater input is already total cell power; modal projection must not
multiply it by cell area a second time. Observations are point-temperature
interpolations at the source-defined sensor coordinates and active mid-depth,
not claimed measurements of a finite sensor's area-average temperature.

The separated and sparse solves differ on the original 3,361-node grid by at
most `9.27e-11 K` across the 13 nominal patterns. A separate nonuniform small
fixture also checks every node, local equations and heat balance. The constant
source, bath offset, source depth allocation and continuous-z limit have their
own controls. Positive materials and reciprocal face conductances are necessary
physical constraints; none proves that a material value matches the hardware.

## Frozen refinement results

There are 13 fixed power patterns in each of two cooling material sets, tested
on 13 distinct mesh configurations per group (338 pattern/grid combinations).
These are numerical controls, not 338 new measured experiments.

| Coupled level | Max xy pitch (um) | Active/bulk/pad cells | Natural max difference (K) | Fan max difference (K) |
|---|---:|---|---:|---:|
| 0 | 500 | 1 / 2 / 2 | 1.672827 | 1.695576 |
| 1 | 250 | 2 / 4 / 4 | 0.675000 | 0.682401 |
| 2 | 125 | 4 / 8 / 8 | 0.108233 | 0.109656 |
| 3 | 62.5 | 8 / 16 / 16 | 0.068158 | 0.068763 |
| 4 | 31.25 | 16 / 32 / 32 | 0.019554 | 0.019725 |

All differences are against the fixed 1024-order layered-continuum reference
at the same 16 sensor points. Its last series change is 0.001291 K, not a rigorous
truncation bound. The final coupled-grid changes are 0.048665 and 0.049062 K:
both pass the frozen 0.05 K change threshold, with little margin. Every final
sensor difference is below the separate 0.1 K threshold. No extension or
post-result threshold change was needed. This establishes the stated numerical
screen, not an unconditional 0.020 K error guarantee.

Only refining xy leaves 0.734913 / 0.756917 K; only refining z leaves
0.958535 / 0.965175 K (natural / fan). Both directions matter. The single-axis
sequences need not decrease monotonically because the nonuniform feature mesh
and point interpolation change together. Do not add their maximum errors.

An explicit intermediate solution uses continuous z on the same discrete xy
operator. At each sensor/pattern, the signed identity is
`FV - continuum = (FV - continuous_z/discrete_xy) +
(continuous_z/discrete_xy - continuum)`.
This is a path-specific numerical decomposition, not a claim that changing
the two mesh directions has no interaction. At the primary worst point
(`hotspot_2`, sensor 0 at 8960/8960 um), it gives:

| Group | Total (K) | Depth contribution on fixed xy (K) | Remaining lateral/observation contribution (K) |
|---|---:|---:|---:|
| Natural | -1.672827 | -0.734995 | -0.937833 |
| Fan | -1.695576 | -0.756162 | -0.939413 |

At the final worst point (`hotspot_3`, sensor 4 at 6400/8960 um), the respective
contributions are -0.005982/-0.013573 K and -0.006084/-0.013642 K. The identity
holds to displayed floating-point precision on every saved sensor/pattern.

The finest mesh is 328 x 332 x 80, equivalent to 8,711,681 nodes including bath.
All 108,896 lateral modes remain. Each group took about 0.6 seconds for its
finest 16 x 16 steady transfer on this local machine; this timing is not an
equal-budget optimization benchmark or a speed claim for general geometry.
Final numerical controls include:

- Mass-orthogonality error below `1.2e-13`, eigen-equation residual below `2.5e-16`.
- Vertical normalized backward residual below `3.5e-16`.
- Conservative all-mode condition-number bounds below `8.18e5` / `6.00e5`.
- Uniform-mode heat-balance error below `4.3e-14` and positive sensor response.
- Final maximum spatial-contrast difference 0.017789 / 0.017954 K.

## Independent review and next physical experiment

Two ChatGPT web review rounds checked the design and results. Applied feedback:
separate same-grid algebra verification from continuum convergence; keep source
units and observation coordinates explicit; retain the small threshold margin;
avoid adding maximum errors; and limit the conclusion to steady homogeneous
layers. Review was advisory and did not execute the numerical work.

The key next limitation is **loss of separability**. A finite copper footprint,
local contact, patterned pad or spatially varying air boundary couples lateral
modes. The present solver remains a reference for uniform controls; it cannot
silently become the solver for the full nonuniform package. The next experiment
must use a complete coupled operator (or an equivalently verified interface
coupling), source-traceable copper/pad/fin dimensions and conservative interface
heat exchange. Real pad extent (27 mm), copper extent (60 mm) and the 10.24 mm
die must be distinguished. Air/convection assumptions stay explicit.

Hold the existing 26-run spatial-DC diagnostic windows and source parameters
fixed when comparing the uniform and explicit-boundary models. A better match
would test a boundary hypothesis, not identify a unique mechanism or establish
independent material calibration. Transient convergence, logger observation,
complete Pad/PEX/channel evidence and timing coupling remain open.

## Reproduction

```powershell
. ./tools/windows_env.ps1
$env:PYTHONUTF8='1'
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/closure-cli-fresh
python tools/audit_ttc_numerical_closure.py --output results/physical-calibration/closure-fresh
python tools/render_ttc_numerical_closure.py --input results/physical-calibration/closure-fresh --output <report-directory>
```

The audited run passed 140 tests. The CLI retained 3 W input and 34.188607 C
reference peak, explicitly uncalibrated with timing not run. Production modules
were not changed. See `evidence/local-ttc-numerical-closure.json` for file hashes.
