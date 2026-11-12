# HiTS local backend assessment

HiTS was cloned at `be59924de3f0c1a3d6d134aea411d1264cfa64c6`, with its pinned
3D-ICE `4953952a1ef6d38807ff307212a6f15e5b2ef935` and HotSpot
`9f92256f7a45db6057c809e94fcd224ddad9157a` submodules. The source was unchanged.
The user's local-only instruction takes precedence over HiTS's repository
preference for a Linux CUDA server. No remote experiments were run.

HiTS separates supplied physical equations from numerical execution. This is
a useful integration boundary: retain the current package geometry, die
islands, materials, power and sink assembly, then pass its exact sparse matrix
and forcing to a solver. It cannot by itself supply missing package calibration.

The current Windows host reports Intel UHD Graphics 770, no installed WSL
distribution, and no available NVIDIA/CUDA tool commands. The existing project
Python environment has NumPy/SciPy and PyAMG but no Torch. HiTS's internal
generic CPU equation API works without installing its full GPU-oriented public
package. Its 14 `test_thermal_operator.py` checks passed locally; this is not
the complete HiTS suite or GPU qualification.

## Same-equation smoke experiment

The three saved coarse witnesses (nominal, TX power ×1.25, cooling h=800) each
have 784 active solid nodes. `compare_hits_cpu.py` transfers the exact current
package matrix and power vector, in temperature-rise coordinates with explicit
units and per-layer regions. It does not regularize die voids or alter the
boundary. Capacity is absent for the steady query. All three generic HiTS
GMRES solves passed the original-equation check at its unchanged defaults.

| Profile | Maximum temperature difference K | Direct solve s | HiTS solve API s |
|---|---:|---:|---:|
| nominal | 2.010e-8 | 0.001676 | 0.525640 |
| TX power ×1.25 | 2.284e-8 | 0.001421 | 0.550116 |
| cooling h=800 | 2.424e-8 | 0.001383 | 0.671747 |

These are single-run smoke timings. Assembly is excluded from both; the HiTS
API includes its own validation and context closing. They are not statistically
controlled performance measurements, GPU timings, or a 3D-ICE comparison.
Maximum energy-balance error was 1.53e-9 W. This is solver consistency, not
independent physical validation. An initial adapter attempt supplied four
dependency labels; HiTS correctly rejected it because its contract requires
exactly three labels for A, M and b. The final adapter declares them separately.

The evidence is [saved here](evidence/local-hits-cpu-smoke.json). Reproduce:

```powershell
. ./tools/windows_env.ps1
python tools/compare_hits_cpu.py --hits PATH_TO_HITS --witness results/physical-calibration/integrated-witness-v1 --output results/hits-cpu-smoke.json
```

## Decision

Retain the direct solver for this small benchmark. Keep HiTS as an optional
equation-level comparison; do not advertise its generic CPU path as acceleration.
The selected GPU solid/package path requires complete square solid planes,
which the current conformal die-island mesh does not directly provide. A fast
backend needs explicit qualification of that topology, not silent material
filling or replacement with a different thermal model.

3D-ICE's pinned source is present but its native executable was not built or
timed in this stage. A meaningful future comparison should distinguish two
experiments: identical assembled equations with different numerical backends,
and independently assembled models with matched physical boundaries and
observations. Include assembly/setup, repeated-query costs, memory and paired
layout differences before selecting a production path. No hardware or global
environment installation was attempted.
