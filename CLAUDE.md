# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `AGENTS.md` first.** It holds the binding project rules: fetch `origin` at
session start, push validated milestones to `main` with `[skip ci]`, keep `main` as
the only branch, follow the physical-admission contract, use 1–3 seeds at most, and
avoid speculative validation work. This file does not repeat those rules.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e .                     # core: numpy, scipy
python -m pip install -e '.[validation]'       # PyYAML, matplotlib, zstandard, pyamg

# Full suite (required before publishing a substantive code/experiment milestone)
python -m unittest discover -s tests -p '*_unittest.py' -v
# Single test file / single test. Use discover -s tests: tests import sibling test
# modules and tools/ by bare name, so `python -m unittest tests/x.py` fails.
python -m unittest discover -s tests -p 'atplace_step_size_unittest.py' -v
python -m unittest discover -s tests -p 'atplace_step_size_unittest.py' -k test_name
# Without an editable install, prefix commands with PYTHONPATH=src

# Documented two-chiplet CLI check (output directory must not already exist)
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/<new-dir>
```

Heavier experiments run on the shared server `eex005`. Reach it from this Mac with
`ssh poweric-jump 'ssh wangziheng@eex005 "..."'`; the second hop's key lives on the jump host,
so `-J` does not work. Workspace: `~/haoning/chiplet_floorplanning`, which already has
`results/physical-calibration/atplace-import-v1/Case1..10.json` imported from `~/haoning/ATPlace_pub`.
Conda env: `~/miniconda3/envs/chiplet-fp` (Python 3.12, `-e '.[validation]'`). Other users
keep its 256 cores busy (load average about 220), so cap process pools at about 24 workers
and set `OPENBLAS_NUM_THREADS=1`. Never `pkill -f <script>` through ssh; the pattern also matches
the remote shell's own command line.

There is no configured linter. CI (`.github/workflows/ci.yml`) also runs the
`tools/validate_*.py` integration scripts. These need OpenSTA, ngspice and others, built by
`tools/bootstrap_validation.py`. Pushes use `[skip ci]`, so these checks only run locally.

## Architecture

- `src/chiplet_floorplanning/` is the small, stable production package (~3.3k lines).
  `model.py` parses and strictly validates the JSON input: units, unknown fields,
  overlap and rotation. The schema is in `docs/model.md`; JSON lengths are mm.
  `power.py` rasterizes block power onto the thermal grid, `thermal.py`/`package.py`
  solve the layered steady-state FV network, and `interconnect.py`/`routing*.py`/`pin_fabric.py`
  handle geometry and RC. `timing.py`, `network_sta.py` and `characterization.py` drive
  OpenSTA. `cli.py` writes `input.json`, `grid.csv` and `report.json`. Thermal and timing calibration status
  are reported as `not_calibrated`/`not_run` and must stay explicit.
- `src/chiplet_floorplanning/placement/` is the refactored placement core for new work:
  an array `Problem`/`Layout`, vectorized legality and source-pin Manhattan length, and the
  declared TAP-family FV recipe solved with scipy (no HiTS). `tests/placement_core_unittest.py`
  checks it against the legacy `tools/atplace_pin_geometry.py`, including exact equality of the
  assembled matrices. New experiments should build on it instead of extending the `tools/atplace_*` chain.
- `tools/` holds research code and experiment drivers (~150 scripts), not a package.
  Scripts import each other by bare module name, so run them from the repo root with
  `tools/` on the path, the same way the tests set it up. Naming:
  `run_*` executes an experiment, `validate_*`/`audit_*`/`check_*` verify things,
  `freeze_*`/`prepare_*` build inputs, and `report_*`/`render_*`/`plot_*`/`summarize_*` produce outputs.
  `tools/validation/` has shared fixtures. `*.lock.json` pin external sources.
- Current research line: **ATPlace Case1 search** (`tools/atplace_*.py`, `tools/run_atplace_*.py`),
  built on the earlier TAP online search (`tap_online.py`, `tap_r3_metrics.py`). Thermal
  queries go to the external HiTS solver through `tools/solve_tap_fv_hits.py`, passed in with
  `--hits` and kept under `local/`. Each experiment is a chain of modules that each extend the previous
  stage, e.g. `run_atplace_step_size` → `run_atplace_tight_budget` → `atplace_temperature_feedback`
  → `atplace_orientation_repair` / `atplace_incremental_pins`.
- Experiment protocol pattern: `run_atplace_<x>.py --freeze` writes a frozen plan to
  `docs/evidence/atplace-case1-<x>-plan-v1.json`, including source hashes and a response-cache
  hash. `--execute --hits ... --output results/...` runs it. `--verify` replays the
  committed result without new thermal queries. Each stage has its own docs:
  `docs/atplace-case1-<x>-protocol.md`, `-results.md` and, after a Chat review, `-review.md`.
  Do not change a frozen plan after the fact. Start a new version instead.

## Research records

- `docs/overall-research-status.md` is the cumulative acceptance table; update it with each
  milestone. `docs/evidence/research-record-index.json` indexes all committed records.
- Metric contract: `docs/tap-r3-metrics.md`. The main metric is paired peak temperature under
  a shared interconnect budget; the reverse metric is interconnect cost under a temperature cap.
  The interconnect cost is a Manhattan pin/centre-distance proxy, not routed wirelength or timing.
- Docs and the README are written mostly in Chinese. Match that language when editing them.
- Raw results go in `results/`; external sources, solvers and PDKs go in `local/`. Both are gitignored.
