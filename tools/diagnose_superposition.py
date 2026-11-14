"""Measure the superposition surrogate against exact FV peaks on sampled legal layouts.

Diagnostic only: decides whether the surrogate may rank candidates for a search.
Reported layouts are always FV-evaluated; the surrogate never becomes a result.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import kendalltau, spearmanr

from chiplet_floorplanning.placement import Evaluator, Problem, Superposition, pareto_front, sample_legal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=2026111300)
    parser.add_argument('--gap-um', type=float, default=1000)
    parser.add_argument('--resolution', type=int, default=64, help='FV reference mesh')
    parser.add_argument('--kernel-resolution', type=int, default=96)
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    problem = Problem.from_imported(json.loads(args.case.read_text()))
    rng = np.random.default_rng(args.seed)
    layouts = [sample_legal(problem, args.gap_um, rng) for _ in range(args.samples)]
    evaluator = Evaluator(problem, args.gap_um, args.resolution, args.workers)
    started = time.perf_counter()
    fv = evaluator.peaks_c(layouts)
    fv_seconds = time.perf_counter() - started
    started = time.perf_counter()
    model = Superposition(problem, args.gap_um, args.kernel_resolution)
    kernel_seconds = time.perf_counter() - started
    started = time.perf_counter()
    approx = np.array([model.peak_c(layout) for layout in layouts])
    surrogate_seconds = (time.perf_counter() - started)/len(layouts)
    length = np.array([evaluator.length_m(layout) for layout in layouts])
    error = approx - fv
    top = max(1, len(layouts)//20)
    best_fv, best_approx = set(np.argsort(fv)[:top]), set(np.argsort(approx)[:top])
    front = pareto_front(length, fv)
    summary = dict(
        case=problem.name, samples=len(layouts), seed=args.seed, gap_um=args.gap_um,
        fv_resolution=args.resolution, kernel_resolution=args.kernel_resolution,
        distinct_fv_solves=evaluator.solves, fv_wall_seconds=fv_seconds, workers=args.workers,
        kernel_build_seconds=kernel_seconds, surrogate_seconds_per_layout=surrogate_seconds,
        fv_peak_c=dict(min=float(fv.min()), median=float(np.median(fv)), max=float(fv.max())),
        error_k=dict(mean=float(error.mean()), std=float(error.std()), max_abs=float(abs(error).max()),
                     max_abs_after_mean_shift=float(abs(error - error.mean()).max())),
        spearman=float(spearmanr(fv, approx).statistic), kendall=float(kendalltau(fv, approx).statistic),
        top5pct_overlap=len(best_fv & best_approx)/top,
        fv_argmin_surrogate_rank=int(np.argsort(np.argsort(approx))[int(np.argmin(fv))]),
        fv_pareto_points=len(front),
        front_error_k=[float(error[i]) for i in front],
        scope='declared FV research model; surrogate ignores moving die islands and carrier edges; not calibration')
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    np.savez_compressed(args.output/'samples.npz', centre_um=np.array([l.centre_um for l in layouts]),
                        rotation_deg=np.array([l.rotation_deg for l in layouts]), fv_peak_c=fv,
                        surrogate_peak_c=approx, length_m=length)
    print(json.dumps({k: v for k, v in summary.items() if k != 'front_error_k'}, indent=2))


if __name__ == '__main__':
    main()
