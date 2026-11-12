# Actual cell hierarchy: local-temperature propagation controls

Origin/main was fetched and synchronized at
`7f5869ace6d3059368a10f5513ef88707e669999`. All runs used local Windows CPU
and the previously hashed XyceNF 7.10.0 executable.

The pinned SKY130 cells do not originally forward local operating temperature
to their primitive MOS devices. The diagnostic now makes local copies of the
PDK and the three cell netlists. It adds `cell_temp_c` to the cell interface,
forwards it as `device_temp_c` to every primitive instance, and supplies that
value to the primitive MOS `TEMP` parameter. All model cards remain scoped
inside their original primitive wrappers. No dimensions, model coefficients,
nominal temperatures, connectivity or supplies are adjusted.

Instrumentation rejects unknown primitive types and unexpected wrapper
topology. Removing the declared additions must reconstruct the original text.
All 837 pinned primitive files and each cell hash are checked before copying;
the two transformed primitive files and three transformed cell netlists have
recorded before/after hashes. Only local copies are modified, not the pinned
PDK. This validation helper is not a general-purpose SPICE rewriter.

## Eighteen completed local simulations

For each of `inv_1`, `buf_8` and `dfxtp_1`, two electrically independent copies
receive identical inputs and loads. Six cases compare:

1. Unmodified circuit at global 25 C.
2. Unmodified circuit at global 100 C.
3. Modified circuit with both local temperatures 25 C, global 25 C.
4. Both local temperatures 100 C, global 25 C.
5. Mixed local temperatures 25/100 C, global 25 C.
6. Reversed local temperatures 100/25 C, global 25 C.

The global hot and cold controls must produce distinct timing, preventing an
ignored-temperature implementation from passing by equality alone. Every
modified instance is compared with the appropriate unmodified global control.
The declared 0.05 ps equivalence screen is a numerical implementation check,
not a physical uncertainty bound.

| Cell | Simulations | Largest measured timing/slew mismatch (ps) | Result |
|---|---:|---:|---|
| inv_1 | 6 | 8.89e-13 | Pass |
| buf_8 | 6 | 8.89e-13 | Pass |
| dfxtp_1 | 6 | 6.70e-10 | Pass |

The first two cells use 10 ns stimuli, 0.122474 ns input slew and a
0.0254232 pF output load. The flip-flop uses an 18 ns sequence that first
initializes Q=0, captures 1, then captures 0; its clock/data ramps are 0.2 ns,
data precedes capture by 2 ns, and its output load is 0.0254232 pF. All cases
use 1.8 V and a 1 ps maximum step. Measurements check finite complete
waveforms, intended threshold crossings and settled outputs. Flip-flop
measurements cover clock-to-Q and slew, **not setup/hold characterization**.

These results show that the actual scoped wrappers avoid the mixed-temperature
sharing sensitivity observed with the manufactured shared model card. They
do not establish that every model organization or operating point is safe.
Existing Xyce model-version and primitive-parameter warnings remain present;
they are recorded rather than treated as physical qualification.

Evidence: [inverter](evidence/local-temperature-inverter.json),
[buffer](evidence/local-temperature-buffer.json),
[flip-flop](evidence/local-temperature-ff.json).

## Reproduction and limitations

```powershell
. ./tools/windows_env.ps1
python tools/probe_core_local_temperature.py --cell inv_1 --output results/local-temp-inverter
python tools/probe_core_local_temperature.py --cell buf_8 --output results/local-temp-buffer
python tools/probe_core_local_temperature.py --cell dfxtp_1 --output results/local-temp-ff
```

Model copies use short repository-local paths to avoid Windows include-path
length failures. The initial longer-path attempt failed during include loading
and is retained as `results/physical-calibration/xyce-local-inverter-v1`.
Its partial receipt is not promoted into completed evidence. Raw simulation
decks, models and logs remain local.

Four regression tests check preservation of non-temperature text, rejection
of unknown primitives, duplicate instrumentation, and unsupported primitive
topology. The full 215-test suite and documented two-chiplet CLI passed.

Next bind the evaluated per-instance thermal field to these temperature
parameters and the corresponding heated RC network in the complete fabric.
The one-way fixed-power assumption, core-cell/Pad distinction, setup/hold
constraint scope, and package calibration limitations remain explicit. This
stage validates temperature propagation; it does not yet prove a changed
hot-layout optimum or complete Goal 01.
