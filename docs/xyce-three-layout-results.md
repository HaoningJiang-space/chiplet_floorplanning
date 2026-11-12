# Bounded fabric exit: thermal interaction without ordering reversal

The frozen experiment is complete. For these three fixed layouts **and routes**,
all 96 lane/edge/window pair comparisons and all six minimum-window comparisons
retain their cold ordering after thermal feedback at both tested Xyce steps.
STA agrees with all 96 fine-step cold and hot pair signs, and with the six
minimum-window signs. This is a conditional result within tested models, not a
physical ordering certificate, a slack claim or a global floorplanning optimum.

85 of 96 path comparisons have a resolved nonzero interaction under the
predeclared empirical screen; 11 have no resolved interaction. None has an
unresolved ordering under that screen. A nonzero interaction therefore does
not imply a changed layout choice. No joint-optimizer advantage is established.

## Scope and admission

The manifest and decision convention were published before these hot results
in `b088c9b`; independent STA minimum selection was fixed in `f718f77`.
The unchanged comparator was run at `d180f6688c188523342fb9094a4b8aad51cf85e7`.
It reloaded the raw waveforms, exact CSV identities, source circuit/RC and local
temperature assignments, transformed-model hashes, saved STA identities and
receipt bindings. All three cold and hot runs completed at 5 and 2.5 ps. Each
of these 12 logs contains 2785 recognized warnings and zero unknown or suppressed
diagnostics. Recognizing those model warnings does not prove they are harmless.
Earlier suppressed logs remain preserved and were not retroactively admitted.

Both full-fabric uniform controls were replayed: global/local differences are
at most 0.010178 ps at 25 C and 0.017386 ps at 65 C. Both pass the original
0.5 ps numerical screen. Physical qualification remains false.

The full replayed measurements, path identities, minimum selections, observed
ranges, model comparisons and receipt hashes are in
[the published evidence](evidence/local-xyce-three-layout-comparison.json).
Raw waves, PDK assets and logs remain local; a GitHub reader can audit the
implementation and summary but cannot independently replay those private/local
artifacts from the compact evidence alone.

## Layout-pair results

For A/B define D = W(B)-W(A) and I_T = D_hot-D_cold, all in ps below.
Each pair includes 8 lanes, two edges and setup/hold: 32 correlated entries.
They are not independent statistical samples.

| A / B | Stable / changed / unresolved ordering | Resolved interactions | Fine-step I_T range | Maximum I_T step change | Maximum STA/Xyce I_T difference |
|---|---:|---:|---:|---:|---:|
| rot180 / rot90 | 32 / 0 / 0 | 22 / 32 | -4.5722 to 4.6052 | 0.2970 | 0.1307 |
| rot180 / rot270 | 32 / 0 / 0 | 32 / 32 | -5.7450 to 5.7583 | 0.1316 | 0.2050 |
| rot90 / rot270 | 32 / 0 / 0 | 31 / 32 | -3.6140 to 3.6303 | 0.3297 | 0.2176 |

The smallest absolute cold/hot path-pair gaps across both steps are respectively
2.5445, 45.8699 and 27.4502 ps. All satisfy the frozen sign/magnitude screen;
this does not make the screen a physical error bound.

Re-selecting the minimum window independently for each layout, mode and step:

| A / B | Window | D_cold at 2.5 ps | D_hot at 2.5 ps | I_T observed over both steps | Ordering |
|---|---|---:|---:|---:|---|
| rot180 / rot90 | setup | 21.7051 | 18.8620 | -2.9042 to -2.8432 | stable |
| rot180 / rot90 | hold | 9.5310 | 8.8012 | -0.7299 to -0.4331 | stable |
| rot180 / rot270 | setup | 85.0906 | 82.9401 | -2.1505 to -2.0314 | stable |
| rot180 / rot270 | hold | -77.9600 | -81.4946 | -3.5674 to -3.5347 | stable |
| rot90 / rot270 | setup | 63.3855 | 64.0781 | 0.6926 to 0.8729 | stable |
| rot90 / rot270 | hold | -87.4910 | -90.2958 | -3.1342 to -2.8048 | stable |

All six minimum interactions pass the separate empirical interaction screen.
Critical identities are retained in the evidence; no cold/hot or step-induced
critical-path migration occurs here. Larger setup minimum is ranked
rot270 > rot90 > rot180; larger hold minimum is rot90 > rot180 > rot270,
both cold and hot. There is no single winner without a declared decision rule.

## Numerical, model and physical uncertainty are different

- Numerical: the maximum path-pair interaction step sensitivity is 0.329651 ps.
  The table reports actual two-step ranges, not confidence intervals. Uniform
  controls are separate observations, not bounds for all temperatures/layouts.
- Model: pair-interaction discrepancies are at most 0.217624 ps between STA
  and Xyce at 2.5 ps. However, absolute cold/hot pair-window differences at
  that step disagree by as much as 45.244699 ps. Small interaction discrepancy does not imply small
  absolute model error. Within one layout the largest thermal-change discrepancy
  is 1.319150 ps. All tested signs agree, without certifying untested models.
- Physical: package stack, convection/contact conditions, fixed workload power,
  real PHY/Pad and receiver constraint uncertainty remain unquantified. These
  available windows exclude independently characterized receiver setup/hold
  boundaries and must not be renamed physical slack. Thermal feedback here is
  fixed-power one-way coupling, not a temperature-dependent leakage equilibrium.

From event bookkeeping, setup available window is capture arrival minus data
arrival. A common shift cancels; unequal shifts can increase or decrease it.
Thus warming need not monotonically shrink an available window, even when
individual propagation delays grow. A sorting reversal additionally requires
that differential change to cross the pre-existing layout-pair gap. The
observed nonzero interactions here do not cross those gaps. This explains the
logical distinction; it does not identify a uniquely measured circuit cause.

## Exit and next gate

This completes the explicitly bounded uniform/three-layout fabric experiment.
Do not add isolated-cell experiments or tighten the clock to seek a reversal.
Keep timing as a validation/constraint option; return to sourced floorplanning
geometry, finite package resources and thermal problem structure. The new
[TAP geometry domains](tap-geometry-domains.md) are an input milestone, not a
completed physical benchmark. The need for a new optimizer remains unproven.

Local validation: 248 tests and the documented two-chiplet CLI passed in the
same code state (3 W, 34.1886 C; uncalibrated; timing not run). All experiments
ran locally. Chat review of this complete stage is pending publication; earlier
reviews through ba4fbeb do not cover these results.

Reproduce with the retained local trees:

```powershell
python tools/compare_xyce_hot_layouts.py docs/evidence/xyce-three-layout-manifest.json --output results/physical-calibration/xyce-three-layout-comparison.json
```
