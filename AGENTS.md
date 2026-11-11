# Project instructions

This is the independent `chiplet_floorplanning` repository. Run Git commands
here; do not place these changes in adjacent placement repositories.

- Use Python 3.10+, four spaces, and explicit units in data fields.
- Run `python -m unittest discover -s tests -p '*_unittest.py' -v` and the
  documented two-chiplet CLI case before publishing a milestone.
- Keep numerical checks separate from physical model validation. Missing timing
  and external thermal validation must remain explicit in outputs.
- Commit coherent validated changes and push promptly to the public
  `HaoningJiang-space/chiplet_floorplanning` repository.
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
