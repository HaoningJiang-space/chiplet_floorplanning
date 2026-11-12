# Project instructions

This is the independent `chiplet_floorplanning` repository. Run Git commands
here; do not place these changes in adjacent placement repositories.

- At the start of every new research session, fetch `origin` and inspect remote
  commits before drawing conclusions. Fast-forward a clean, behind `main` when
  possible; preserve local changes and resolve divergence explicitly. Record the
  analyzed commit and whether the fetch succeeded. If offline, label freshness
  unverified. Recheck the remote before publishing; never force-push over new work.
- Use Python 3.10+, four spaces, and explicit units in data fields.
- Match verification to the change. Run focused checks during implementation;
  run `python -m unittest discover -s tests -p '*_unittest.py' -v` and the
  documented two-chiplet CLI before publishing a substantive code/experiment
  milestone. Documentation-only or instruction-only changes need a diff review,
  not another full suite or CLI run. Reuse passing evidence when executable code,
  inputs and relevant assumptions have not changed.
- Keep numerical checks separate from physical model validation. Missing timing
  and external thermal validation must remain explicit in outputs.
- Commit and promptly push coherent validated milestones to origin/main; the
  user explicitly authorized timely pushes on 2026-11-11. Research experiments
  still run locally. Use [skip ci] in the pushed HEAD commit message while this
  local-only execution constraint remains, and verify remote HEAD after pushing.
  Continue fetching for freshness; never force-push over remote work.
- Before a major-stage ChatGPT review, finish local validation, commit, push and
  verify the remote SHA first. Give the reviewer that published SHA so it can
  autonomously inspect actual code/history through GitHub rather than summaries.
- The frozen TTC v2 transient job may finish unchanged. Before any new use of
  --prior-controls, integrate a mandatory control-protocol fingerprint check;
  the retrospective cache audit does not yet enforce future cache admission.
- During long research, commit independently validated local sub-milestones
  promptly. Keep unfinished experiments and failed controls explicitly labeled.
- Maintain `main` as the only branch, locally and on `origin`. Commit validated
  changes directly on `main`; remove development branches after verifying they
  are fully merged.
- Keep credentials, SSH configuration, raw results, environments and restricted
  PDK assets out of the repository. Use `local/` and `results/` for local data.
- Preserve user files and avoid changing global Git identity or authentication.
- Keep production modules and reproducible validation separate. Remove superseded
  temporary code; preserve necessary baselines, negative controls and evidence.
- State physical assumptions and supported domains explicitly. Numerical checks
  alone must never be presented as physical calibration or complete signoff.
- Prioritize the user's physical-law requirement: check conservation, units,
  passivity/causality and boundary/reference-plane definitions before interpreting
  fitted agreement or optimization. Follow `docs/physical-admission-contract.md`;
  necessary invariants do not certify real materials, compact models or channels.

## Research pace and proportional validation (user direction, 2026-11-12)

- Maintain docs/overall-research-status.md as the cumulative research and
  acceptance record. Review cases, physical model, metrics and algorithm
  evidence one bounded item at a time. Record question, inputs/version,
  evidence, accepted scope, gaps and next change. Read original papers' case
  definitions and experimental protocols; distinguish source configuration,
  paper reproduction and our adaptation. This workflow does not add a user
  approval gate or justify repeating already-passing calibration campaigns.

- Lead algorithm comparisons with physical layout quality: peak temperature at
  the same interconnect budget, plus interconnect cost at the same temperature
  ceiling. Freeze common thresholds before new runs; preserve selected joint
  points and attainment status. HV, legal rate and runtime are auxiliary.
  Never combine temperature and distance minima from different layouts or call
  centre-span proxies routed wirelength/timing. Pair by case/seed before taking
  medians. Follow docs/tap-r3-metrics.md for the current exact metric contract.

- Use fewer random seeds. Default to one seed for development/smoke experiments
  and up to three paired seeds for a main algorithm comparison. Do not default
  to five or more. Add seeds only when observed variability or a specific research
  question warrants them, with a short explanation of the expected benefit.
  Keep shared initializations and comparable budgets across methods. This rule
  applies to future experiments; do not silently truncate an already frozen run.
- Prioritize algorithm implementation, meaningful comparisons and larger cases.
  The physical model needs to capture the relevant phenomena and obey basic
  physical laws; manufacturing signoff, exhaustive calibration or unnecessarily
  tight numerical precision must not gate ordinary algorithm progress.
- Avoid excessive defensive work: do not add speculative validation layers,
  repeated audits, redundant tests or new approval steps without a concrete issue
  that could affect correctness or the research conclusion. Fix actual failures
  and keep essential unit, conservation, geometry and fair-comparison checks.
- State material assumptions and limitations clearly in the experiment record;
  do not repeat the same caveats in every progress update. Report meaningful
  results, decisions and actionable failures instead of narrating every poll.
  Check completed-run evidence at useful milestones, not after each extra run.
- Use Chat to guide major research decisions and review completed stages with
  the latest pushed code/history. Do not make each small reversible step wait
  for a review or expand the review into another physics-calibration campaign.
