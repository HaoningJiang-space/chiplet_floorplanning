# Frozen three-layout comparison protocol

The three cold/hot jobs are still running. This protocol is specified before
their paired hot results are available; it is not a result or pass claim.

`tools/compare_xyce_hot_layouts.py` consumes the exact three-layout manifest in
`docs/evidence/xyce-three-layout-manifest.json`. It independently replays raw
cold/hot waveforms through `summarize_xyce_hot.py`, requiring full admitted
diagnostics, unchanged artifact hashes and circuit/temperature assignments. It
also replays both uniform controls. Missing or failed experiments stop report
generation rather than becoming feasible/infeasible observations.

For each pair A/B, report `W(B)-W(A)` cold and hot, and their difference `I_T`.
Keep setup and hold distinct. Evaluate 32 lane/edge/window entries per pair at
both 5 and 2.5 ps; these are correlated measurements, not independent samples.
Also recompute the minimum over all paths for each layout, temperature and step,
recording the critical path identity so a migrating bottleneck is not missed.

The empirical ordering screen requires the pair difference to have the same sign
at both steps and its smallest magnitude to exceed the larger of (a) the observed
step change and (b) twice the maximum observed uniform-control discrepancy.
This is a declared diagnostic convention, not an inferred statistical interval
or rigorous error bound. It is reported alongside the actual values, so users
can inspect the margin without accepting the convention. Failed uniform controls
make the interpretation unresolved. The interaction has a separate resolution
label: a resolvable nonzero interaction does not necessarily change ordering.
For the four-term interaction, its control-discrepancy screening floor is four
times the observed uniform discrepancy. Neither multiplier makes the observed
control discrepancy a bound on untested temperatures, layouts or physical error.

Report the observed interaction range across steps and its step sensitivity,
the STA pair differences, and STA-versus-SPICE interaction discrepancy separately.
The `ordering` label is restricted to the tested Xyce numerical variants;
`fine_model_order_agreement` separately exposes agreement/disagreement with STA.
Package, PHY and material uncertainty remains unquantified. No physical layout
ordering certificate, characterized slack, or global-optimum claim is produced.

Once local jobs finish:

```powershell
python tools/compare_xyce_hot_layouts.py docs/evidence/xyce-three-layout-manifest.json --output results/physical-calibration/xyce-three-layout-comparison.json
```

Publish the finite report, including unresolved cases; do not add layouts or
isolated-cell simulations solely to obtain a preferred ordering outcome.
