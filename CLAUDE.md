# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `AGENTS.md` first.** It holds the binding project rules: fetch `origin` at
session start, push validated milestones to `main` with `[skip ci]`, keep `main` as
the only branch, follow the physical-admission contract, use 1–3 seeds at most, and
avoid speculative validation work. This file does not repeat those rules.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e .                     # numpy, scipy only

# Full suite (required before publishing a substantive code/experiment milestone)
python -m unittest discover -s tests -p '*_unittest.py' -v
# Single test file / single test. Use discover -s tests: tests import sibling test
# modules and tools/ by bare name, so `python -m unittest tests/x.py` fails.
python -m unittest discover -s tests -p 'placement_core_unittest.py' -v
python -m unittest discover -s tests -p 'placement_core_unittest.py' -k test_name
# Without an editable install, prefix commands with PYTHONPATH=src

# Documented two-chiplet CLI check (output directory must not already exist)
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/<new-dir>
```

Heavier experiments run on the shared server `eex005`. Reach it from this Mac with
`ssh poweric-jump 'ssh wangziheng@eex005 "..."'`; the second hop's key lives on the jump host,
so `-J` does not work. Workspace: `~/haoning/chiplet_floorplanning`, which already has
`results/physical-calibration/atplace-import-v1/Case1..10.json` imported from `~/haoning/ATPlace_pub`.
Conda env: `~/miniconda3/envs/chiplet-fp` (Python 3.12, editable install). Other users
keep its 256 cores busy (load average about 220), so cap process pools at about 24 workers
and set `OPENBLAS_NUM_THREADS=1`. Never `pkill -f <script>` through ssh; the pattern also matches
the remote shell's own command line.

HTTPS pushes use the gh OAuth token, which lacks the `workflow` scope. Push commits that touch
`.github/workflows/` with `git push git@github.com:HaoningJiang-space/chiplet_floorplanning.git main`.

There is no configured linter. CI runs the unit tests and both example CLI evaluations;
pushes use `[skip ci]`, so run those checks yourself.

## Architecture

The repository was cut down on 2026-11-13 to what current work uses. Earlier research
lines (TTC, Pad/SPICE, OpenSTA timing, Xyce, TAP/HiTS search, the staged `atplace_*`
Case1 chain) were deleted from HEAD. Their results stay in `docs/`; their code runs at its
own commit through `tools/replay_at_commit.py` (see `docs/code-history-and-replay.md`).
Delete unused code instead of keeping it around; do not rebuild per-stage `run_*` chains.

- `src/chiplet_floorplanning/placement/` is the placement core for all new work. `Problem` holds
  arrays from an imported ATPlace case (µm, W), and `Layout` holds centres and quarter-turn rotations.
  `geometry.py` has vectorized legality (carrier bounds plus a minimum gap) and the two-pin
  Manhattan length lower bound. `thermal.py` builds the declared TAP-family FV package
  (100 mm spreader, 200 mm sink, top Robin h) and solves it with scipy, at about 0.25 s per Case1 layout.
- `model.py` → `mesh.py` → `power.py` → `package.py`/`thermal.py` form the generic JSON-case
  thermal pipeline used by both `placement/thermal.py` and `cli.py`. `model.py` strictly validates
  units and unknown fields (schema in `docs/model.md`, JSON lengths in mm). The CLI writes
  `input.json`, `grid.csv` and `report.json`. Thermal calibration and timing stay explicitly `not_run`.
- `evaluate.py` has the `Evaluator` (exact FV peak with a thermal-key cache and a persistent process
  pool when used as a context manager), the constructive legal sampler, and the metric selectors
  (`coolest_within`, `shortest_within`, `pareto_front`). Each returns one real layout.
  `search.py` has legal moves, exact length descent and batched Pareto local search.
  `surrogate.py` (shifted single-chip FV kernels) ranks well but is biased by about 1.8 K, so use it only to screen.
- `tools/run_reference_front.py` (budget `--fv-solves` = distinct FV solves, start set included) and `tools/diagnose_superposition.py`
  run on eex005. `tools/import_atplace_cases.py` imports ATPlace Case1–10 at pinned source commit `fe3dbfd`.

## Research records

- `docs/overall-research-status.md` is the cumulative acceptance table; update it with each
  milestone. `docs/evidence/research-record-index.json` indexes all committed records.
- Metric contract: `docs/tap-r3-metrics.md`. The main metric is paired peak temperature under
  a shared interconnect budget; the reverse metric is interconnect cost under a temperature cap.
  The interconnect cost is a Manhattan pin/centre-distance proxy, not routed wirelength or timing.
- Docs and the README are written mostly in Chinese. Match that language when editing them.
- Raw results go in `results/`; external sources, solvers and PDKs go in `local/`. Both are gitignored.
