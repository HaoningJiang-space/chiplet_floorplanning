# Project instructions

This is the independent `chiplet_floorplanning` repository. Run Git commands
here; do not place these changes in adjacent placement repositories.

- At the start of every new research session, fetch `origin` and inspect remote
  commits before drawing conclusions. Fast-forward a clean, behind `main` when
  possible; preserve local changes and resolve divergence explicitly. Record the
  analyzed commit and whether the fetch succeeded. If offline, label freshness
  unverified. Recheck the remote before publishing; never force-push over new work.
- Use Python 3.10+, four spaces, and explicit units in data fields.
- Run `python -m unittest discover -s tests -p '*_unittest.py' -v` and the
  documented two-chiplet CLI case before publishing a milestone.
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
