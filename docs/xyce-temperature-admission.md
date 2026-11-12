# Xyce local-temperature admission experiment

Freshness: origin/main was fetched successfully at
`e83d5e0af2b6f83a0014d6e11b9976b6de430ece`, with no divergence. Experiments
ran locally on Windows CPU. No production timing backend was changed.

The official [Xyce executable distribution](https://xyce.sandia.gov/downloads/executables/)
provided XyceNF 7.10.0. Its Windows NSIS archive was extracted into repository
`local/xyce-7.10/portable`, without running the installer or changing global
PATH. Binaries remain untracked. This is the distributed NF executable, not
a claim of a locally compiled open-source build.

| Artifact | SHA256 |
|---|---|
| Downloaded Windows ZIP | e3073b6335a43ecc732f56944806005c99b1a378c7d21e293779ae05453b955a |
| Extracted installer | 31235aeb5c818cb3c173294cda417dc8482362fabc4e9d7dbaf2ccc3db9b1637 |
| Executed Xyce.exe | e1f572cd2406bc04b8fbbddba85931346e6ab2b5f0750563848fcabecb10dfe1 |

## Controls and findings

Two electrically independent manufactured NMOS devices have identical bias
(VD=0.5 V, VG=1.2 V), L=0.15 um and W=1 um. Six cases test global 25/100 C,
both instances TEMP=100, both DTEMP=75 at ambient 25, and mixed 25/100 C in
both assignments. Both devices share the same gate supply but have independent
drain supplies; neither electrically influences the other's current.

The warning-free version uses explicit BSIM4 4.8.2, with pbswgs=pbswgd=0.1.
These are manufactured controls, **not modifications of a PDK**. The initial
4.8.1 probe was rejected because the executable substituted 4.8.2 and clamped
default junction parameters. Its raw failed admission evidence is retained.

| Model-card organization | Uniform local/global equivalence | Mixed-temperature independence |
|---|---|---|
| One shared card | Pass | Fail |
| Two cards with exactly identical parameters | Pass | Pass, including reversed temperature assignment |

With one shared card, the hot device in the mixed case draws -0.363918557 mA
instead of the global-hot control's -0.365579683 mA. Reversing the assignment
gives the cold second device -0.444273694 mA instead of -0.442245058 mA.
With separate identical cards, both currents reproduce the corresponding
global controls within the declared 1e-9 relative / 1e-15 A absolute tolerance.
The shared-card discrepancy exceeds that tolerance by many orders of magnitude.
Changing the card organization changes no intended circuit physics. This
isolates a simulator model-sharing sensitivity in this tested configuration;
it is not a quantitative claim about all BSIM models or actual chiplets.

Evidence: [shared-card negative control](evidence/local-xyce-temperature-shared.json),
[separate-card control](evidence/local-xyce-temperature-separated.json).
Each records actual currents and source/deck/output/log/executable hashes.
Admission requires clean logs as well as numerical equivalence, and failed
controls return a nonzero exit status.

## PDK compatibility remains open

The actual pinned SKY130 nfet_01v8 primitive wrapper declares BSIM4 version
4.5. A further manufactured probe with that declaration produces an explicit
warning: Xyce substitutes its oldest supported version, 4.6.1. This probe is
[rejected](evidence/local-xyce-temperature-bsim45.json), even though the program
exits zero and generates currents. Therefore the passing 4.8.2 experiment
does not admit unchanged SKY130 circuits or certify hot timing.

Next compare the actual fixed PDK circuit at uniform 25 C and 100 C across
the existing ngspice reference and an explicitly declared Xyce implementation.
Report version substitution as a model difference; assess its effect on
paired layout decisions rather than requiring universal zero error. Any
nonuniform-temperature experiment must preserve model-card isolation and
temperature propagation through the real primitive wrappers. No model
parameter fitting, TNOM replacement, or warning suppression is justified by
these controls. Pad/ESD, receiver constraints and package calibration remain
separate requirements.

## Reproduce

After extracting the official Windows executable locally:

```powershell
. ./tools/windows_env.ps1
python tools/probe_xyce_temperature.py --output results/xyce-shared
# Expected nonzero: shared-model mixed-temperature controls fail.
python tools/probe_xyce_temperature.py --separate-models --output results/xyce-separated
# Expected zero for the recorded Xyce executable.
python tools/probe_xyce_temperature.py --bsim-version 4.5 --separate-models --output results/xyce-bsim45
# Expected nonzero: explicit version substitution warnings.
```

The existing full suite and documented two-chiplet CLI were rerun for this
milestone. These checks protect the existing evaluator; they do not validate
the physical fidelity of the new simulator.
