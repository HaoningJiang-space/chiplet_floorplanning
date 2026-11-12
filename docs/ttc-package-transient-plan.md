# Frozen transient package diagnostic

Starting commit `fc25977`; successful origin fetch still reports `c124aa9`.
The full steady package refinement is already running and must not be restarted
merely because an observation times out. This distinct local experiment uses
the same physical G, C, B, H and source parameters; no material or air fit.

The question is whether stored heat in the explicit copper/fin structure alters
the spatial sensor contrast in the previously selected 9-second windows. The
prior natural-cooling sensor mean slopes reach 0.536 K/s even while differences
are comparatively stable. A time-constant lower bound alone cannot determine
mode excitation or sensor error; compute actual transient responses instead.

To propagate the long native 0.1 s records, use congruence/Galerkin projection:
`Cr=V.T C V`, `Gr=V.T G V`, `Br=V.T B`, `Hr=H V`.
Positive C and G imply positive reduced matrices for a full-rank V. This
preserves stability and the collocated source-temperature port passivity.
Point sensors H are not collocated ports and positive/monotone responses are
not guaranteed by that argument. Check them separately. The quadratic Lyapunov
quantity is not the physical stored heat `1.T C theta`.

Force V to contain every body's constant indicator (die, pad, base, each fin).
Their sum contains the global constant vector, so the projected equations retain
global and per-body linear heat balances. Add the instantaneous input directions
`C^-1 B` and shifted steady snapshots `(G+s C)^-1 B`. Use C-weighted orthogonal
projection and retain all independent snapshot directions at tolerance 1e-11.
This is a declared rational snapshot construction, not a reproduction of a
published thermal reduction algorithm. General thermal projection context:
[Hernandez-Becerro et al., 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7847468/).

Freeze nested real shifts (units 1/s):
1. `[0, 1]`;
2. `[0, 0.01, 1, 100]`;
3. `[0, 0.001, 0.01, 0.1, 1, 10, 100, 1000]`.
The instantaneous directions and all body indicators are included at every
order. Further enrichment is allowed only after a preserved numerical failure,
not after judging measured agreement. Keep numerical reduction convergence
separate from spatial mesh convergence and physical accuracy.

Run C and P, both material/cooling groups, at full-network levels 0 and 1 first.
Use all 26 measured records at native 0.1 s, unsmoothed, interval-end observation
as selected from the original source code. Hardware logger timing remains
unverified. Keep the prior start rows, ambient readings and calibration/held-out
labels. The approximately 47 W sixteen cases remain explicitly out of the
source <40 W boundary domain; they belong to calibration, so each group retains
9 domain-eligible held-out patterns. No new measured-data holdout is claimed.

Keep two conditional initial states for every run:
- Static field at the first 10 samples' mean power plus one common temperature
  offset matching the first measured sensor mean. After this offset the whole
  system is generally not in equilibrium; this is intentional and explicit.
- Every node at the first measured sensor mean.

No extra body initial temperature is fitted. Unknown true initial copper/fin
temperatures remain a physical limitation. Propagate every reduced mode exactly
for each piecewise-constant power interval. Record input energy, heat loss,
storage changes and per-body net flux over the same intervals. Inspect the
actual derivative of model sensor means, not just an inferred time constant.

Before interpreting measured errors, verify:
- Full-source steady response is preserved; matrix/orthogonality/positivity and
  block-balance checks. Unit positive steps sampled from microseconds to 2000 s
  must disclose any negative/nonmonotone point response.
  Check both full-field DC reconstruction and C-weighted initial-state projection
  errors. The 32 heaters are paired into the 16 measured electrical inputs with
  the source's fixed half-power allocation; all recorded inputs lie in that
  declared span. This does not independently validate within-pair heating.
- Frequency responses at withheld imaginary shifts `i*[.003,.03,.3,3,30,300]`
  against full sparse complex solves, for all 13 nominal source patterns.
- Independent full-network backward Euler on all 13 nominal patterns: baseline
  0.2 W/channel, on at 0 s, off at 0.5 s, observe every 0.1 s for 1 s.
  Use dt=.005/.0025/.00125 s, retain raw BE results and first-order Richardson
  estimates. Require the two extrapolated references to change by <0.01 K and
  the finest ROM to differ from the finest extrapolate by <0.02 K. Extrapolation
  is a numerical reference, not a physical model or a rigorous error bound.
  Apply the same 0.01/0.02 K thresholds to capacity-weighted body mean
  temperatures. Compare reconstructed interface/anchor flows to the per-body
  projected fluxes, and retain full-order BE's own heat ledger.
- Middle-to-fine ROM differences on the 26 native traces <0.01 K, plus <0.01 K
  withheld-frequency absolute response error. Failure remains visible.

These tests do not alone guarantee all possible inputs, transients or geometry.
Report original raw FV-transient predictions, every reduction order and initial
state, common and spatial residuals, and DC-window transient-versus-steady
contrast. Do not apply the earlier steady-continuum correction to a transient.
No physical calibration, qualified thermal-timing coupling or SOTA claim follows
until remaining measurement, boundary and mesh gates are supported by evidence.
