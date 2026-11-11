Current routing counterfactual: [v0.7](validation-v07.md); pad-model failures:
[v0.6](validation-v06.md); open-case checks: [v0.5](validation-v05.md). Earlier records below
are historical milestones and retain their original scope/limitations.

# v0.1.0 validation receipt

Local validation date: 2026-11-11 (UTC).

Environment: Python 3.12.3, NumPy 2.5.4, SciPy 1.18.1 in an isolated virtual
environment. This record covers numerical and software behavior only.

## Commands

```bash
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two_chiplets
```

The 15 unit/integration tests passed. They cover all four rotations, non-square
die geometry, rotated power locations, boundary touching, 20 invalid-input
mutations, duplicate JSON keys, 12 rotation/mesh power-conservation combinations,
hand-computed partial coverage, and transformed link endpoints.

Thermal tests include zero-power equilibrium, the uniform-power analytic
solution on five grids (including single-row/column cases), an independently
solved two-node network, symmetry, superposition, heat balance and invalid
power arrays. Artifact tests exercise the CLI, input snapshot hash, explicit
missing-timing status and refusal to overwrite an existing output directory.

## Synthetic two-chiplet run

Normalized input SHA-256:
`df949e1d36dffbcdefbba89c40c5deb6ad839894a5a70ebe00dd80deb8e626ba`.

| Quantity | Result |
| --- | --- |
| Grid | 48 × 32 |
| Declared / mapped power | 3.0 / 3.0 W |
| Power mapping error | 0.0 W |
| Reference peak temperature | 34.1886068258 °C |
| Reference mean temperature | 28.125 °C |
| Absolute heat-balance error | approximately 5.02e-14 W |
| Linear residual infinity norm | approximately 6.66e-16 W |
| Data / clock Manhattan length | 3.0 / 3.0 mm |
| Assumed R / C per link | 0.3 ohm / 0.6 pF |
| Thermal package calibration | not performed |
| External thermal comparison | not performed |
| Cross-die setup/hold | not implemented |

Floating-point residuals may vary by platform. The temperature and RC values
are consequences of the synthetic input assumptions; they are not PDK-,
SPICE-, package-, or hardware-validated results. Initial development runs have
no source commit; subsequent runs on a committed checkout record the source
revision in `report.json`. Raw outputs are excluded from Git and regenerated
using the example and commands above.
