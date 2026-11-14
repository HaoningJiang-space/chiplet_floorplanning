"""Approximate reference (length, FV peak) front for one imported case.

Start set: random legal layouts plus exact-length descents from random layouts
(no thermal cost). Then batched Pareto local search with exact FV peaks. The
budget unit is distinct FV solves, including the start set; layouts sharing an
already-solved thermal problem are counted separately. If no legal start can be
built, a failure summary is written instead of retrying forever.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.placement import (Evaluator, Problem, coolest_within, pareto_front,
                                             sample_legal, shortest_within)
from chiplet_floorplanning.placement.methods import Run, pareto_local_search
from chiplet_floorplanning.placement.search import length_descent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=2026111300)
    parser.add_argument('--fv-solves', type=int, default=12000, help='budget: distinct FV solves')
    parser.add_argument('--random-starts', type=int, default=96)
    parser.add_argument('--descent-starts', type=int, default=96)
    parser.add_argument('--batch', type=int, default=96)
    parser.add_argument('--gap-um', type=float, default=1000)
    parser.add_argument('--resolution', type=int, default=64)
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--length-caps-m', type=float, nargs='*', default=[])
    parser.add_argument('--peak-caps-c', type=float, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    problem = Problem.from_imported(json.loads(args.case.read_text()))
    rng = np.random.default_rng(args.seed)
    source = source_revision()
    commit = source['commit']
    started = time.perf_counter()
    try:
        initial = [sample_legal(problem, args.gap_um, rng) for _ in range(args.random_starts)]
        initial += [length_descent(problem, sample_legal(problem, args.gap_um, rng), rng, args.gap_um)
                    for _ in range(args.descent_starts)]
    except RuntimeError as error:
        failure = dict(case=problem.name, status='failed_initialization', error=str(error), seed=args.seed,
                       gap_um=args.gap_um, case_sha256=hashlib.sha256(args.case.read_bytes()).hexdigest(),
                       code_commit=commit, code_dirty=source['dirty'])
        (args.output/'summary.json').write_text(json.dumps(failure, indent=2) + '\n')
        raise SystemExit(f'{problem.name}: {error}')
    descent_seconds = time.perf_counter() - started
    with Evaluator(problem, args.gap_um, args.resolution, args.workers) as evaluator:
        run = Run(evaluator, args.fv_solves)
        pareto_local_search(run, initial, rng, args.batch)
        solves = evaluator.solves
    layouts = run.layouts
    length, peak, _ = run.arrays()
    die_peak, max_net = run.local()
    wall = time.perf_counter() - started
    front = pareto_front(length, peak)

    def point(i):
        return None if i is None else dict(index=i, length_m=float(length[i]), peak_c=float(peak[i]),
                                           max_net_mm=float(max_net[i]),
                                           die_peak_c=dict(zip(problem.names, map(float, die_peak[i]))))
    summary = dict(
        case=problem.name, status='completed', seed=args.seed, budget_unit='distinct FV solves',
        fv_solve_budget=args.fv_solves, distinct_fv_solves=solves, distinct_layouts=len(layouts),
        case_path=str(args.case), case_sha256=hashlib.sha256(args.case.read_bytes()).hexdigest(),
        random_starts=args.random_starts, descent_starts=args.descent_starts, batch=args.batch,
        code_dirty=source['dirty'], stop_reason=run.stop_reason,
        workers=args.workers, wall_seconds=wall, start_descent_seconds=descent_seconds,
        gap_um=args.gap_um, fv_resolution=args.resolution, grid_um=1000,
        code_commit=commit,
        front=[point(i) for i in front],
        coolest_within_length_cap={str(c): point(coolest_within(length, peak, c)) for c in args.length_caps_m},
        shortest_within_peak_cap={str(c): point(shortest_within(length, peak, c)) for c in args.peak_caps_c},
        scope='approximate reference front of the declared FV model and two-pin length lower bound; '
              'not routed wirelength, timing or calibrated temperature')
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    np.savez_compressed(args.output/'layouts.npz', centre_um=np.array([l.centre_um for l in layouts]),
                        rotation_deg=np.array([l.rotation_deg for l in layouts]), length_m=length, peak_c=peak,
                        die_peak_c=die_peak, max_net_mm=max_net, die_names=np.array(problem.names))
    print(json.dumps({k: summary[k] for k in ('distinct_fv_solves', 'distinct_layouts', 'wall_seconds', 'coolest_within_length_cap',
                                              'shortest_within_peak_cap')}, indent=2))
    print('front:', [(round(p['length_m'], 3), round(p['peak_c'], 4)) for p in summary['front']])


if __name__ == '__main__':
    main()
