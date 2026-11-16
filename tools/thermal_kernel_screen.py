"""Error of a superposition thermal kernel against the FV model (plan: docs/thermal-kernel-screen-plan.md).

Each die's kernel is the power-layer rise of that die alone (1 W, centred on the carrier, per quarter-turn parity);
a layout's temperature at a point is the ambient plus the power-weighted kernels shifted to the die centres.
The predicted layout peak (max over 5x5 points inside every die) is compared with the FV die-peak maximum.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.stats import spearmanr

from chiplet_floorplanning.placement import Layout, Problem, sample_legal, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import AMBIENT_C, PACKAGE_MM, die_peaks_c

RESOLUTION = 64
POINTS = np.linspace(-0.4, 0.4, 5)
PER_FRONT = RANDOM = 20


def single(problem, k, turn, gap_um):
    """Power-layer rise (K/W) of die k alone, centred, as an interpolator over package mm."""
    alone = Problem(problem.name, (problem.names[k],), problem.size_um[k:k + 1], np.ones(1), problem.carrier_um,
                    np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
    centre = np.array(problem.carrier_um)[None]/2
    _, rise, edges = solve(thermal_case_data(alone, Layout(centre, np.array([turn])), gap_um, RESOLUTION))
    xc, yc = (edges[0][:-1] + edges[0][1:])/2, (edges[1][:-1] + edges[1][1:])/2
    return RegularGridInterpolator((yc, xc), rise, bounds_error=False, fill_value=0.0)


def kernels(problem, gap_um):
    return {(k, t): single(problem, k, t, gap_um) for k in range(problem.count) for t in (0, 90)}


def sample_points_um(problem, layout):
    """(n, 25, 2) points inside each die (5x5 at -0.4..0.4 of its rotated size)."""
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    grid = np.stack(np.meshgrid(POINTS, POINTS), -1).reshape(-1, 2)
    return layout.centre_um[:, None] + grid[None]*size[:, None]


def predicted_peak_c(problem, layout, table):
    """Kernel-superposition peak over the sample points of all dies, degC."""
    points = sample_points_um(problem, layout).reshape(-1, 2)
    centre_pkg = PACKAGE_MM/2
    rise = np.zeros(len(points))
    for j in range(problem.count):
        if problem.power_w[j] == 0:
            continue
        shifted = (points - layout.centre_um[j])/1000 + centre_pkg     # die j's kernel was solved centred
        rise += problem.power_w[j]*table[(j, int(layout.rotation_deg[j] % 180))](shifted[:, ::-1])
    return AMBIENT_C + float(rise.max())


def fv_peak_c(args):
    problem, layout, gap_um = args
    _, rise, edges = solve(thermal_case_data(problem, layout, gap_um, RESOLUTION))
    return float(die_peaks_c(problem, layout, rise, edges).max())


def screen_case(name, problem, front, gap_um, rng, pool):
    layouts = [front[i] for i in sorted(set(np.linspace(0, len(front) - 1, PER_FRONT).round().astype(int)))]
    n_front = len(layouts)
    layouts += [sample_legal(problem, gap_um, rng) for _ in range(RANDOM)]
    table = kernels(problem, gap_um)
    pred = np.array([predicted_peak_c(problem, l, table) for l in layouts])
    fv = np.array(list(pool.map(fv_peak_c, [(problem, l, gap_um) for l in layouts])))
    err = pred - fv
    row = dict(layouts=len(layouts), front_layouts=n_front, median_abs_k=float(np.median(np.abs(err))),
               p90_abs_k=float(np.percentile(np.abs(err), 90)), mean_bias_k=float(err.mean()),
               p90_debiased_k=float(np.percentile(np.abs(err - err.mean()), 90)),
               spearman_all=float(spearmanr(pred, fv)[0]), spearman_front=float(spearmanr(pred[:n_front], fv[:n_front])[0]),
               fv_range_front_k=float(np.ptp(fv[:n_front])))
    row['usable'] = row['spearman_all'] >= 0.9 and row['p90_debiased_k'] <= 2.0
    print(name, {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}, flush=True)
    return row


def verdict(rows):
    ok = sum(r['usable'] for r in rows.values())
    return 'usable' if ok >= 6 else 'not_usable' if len(rows) - ok >= 4 else 'partial'


def load_front(case_path, run_dir):
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    summary = json.loads((run_dir/'summary.json').read_text())
    z = np.load(run_dir/'layouts.npz')
    front = [Layout(z['centre_um'][p['index']], z['rotation_deg'][p['index']]) for p in summary['front']]
    return problem, front, summary['gap_um']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', nargs=3, action='append', metavar=('NAME', 'CASE_JSON', 'RUN_DIR'), required=True)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    rng = np.random.default_rng(args.seed)
    rows = {}
    with ProcessPoolExecutor(args.workers) as pool:
        for name, case, run in args.case:
            problem, front, gap = load_front(case, Path(run))
            rows[name] = screen_case(name, problem, front, gap, rng, pool)
    out = dict(plan='docs/thermal-kernel-screen-plan.md', verdict=verdict(rows), cases=rows)
    args.output.write_text(json.dumps(out, indent=1) + '\n')
    print(out['verdict'])


if __name__ == '__main__':
    main()
