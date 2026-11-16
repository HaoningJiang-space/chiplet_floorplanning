"""Error of superposition thermal kernels against the FV model (plan: docs/thermal-kernel-screen-plan.md, v2).

Anchor kernel: for each die size and quarter-turn parity, the power-layer rise of that die alone (1 W) at 5x5 anchor
centres over its feasible range; a die at c is the bilinear blend of its four surrounding anchor fields, each shifted
by (c - anchor). Diagnostic floor: each die alone at its actual centre, solved exactly, then superposed - what any
per-die superposition misses is only the better conduction of the other dies. Both are compared with the FV die-peak
maximum at 5x5 points inside every die.
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
ANCHORS = 5
PER_FRONT = RANDOM = 20


def to_package_mm(problem, points_um):
    """Carrier um -> package mm (thermal_case_data centres the carrier on the package)."""
    return (np.asarray(points_um) + (PACKAGE_MM*1000 - np.array(problem.carrier_um))/2)/1000


def alone(problem, size_um, power_w=1.0):
    return Problem(problem.name, ('die',), np.array([size_um], float), np.array([power_w]), problem.carrier_um,
                   np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)


def lone_field(args):
    """(rise K, cell centres x, y in package mm) of one die alone at `centre_um` with `turn`, 1 W."""
    problem, size_um, centre_um, turn, gap_um = args
    _, rise, edges = solve(thermal_case_data(alone(problem, size_um), Layout(np.array([centre_um]), np.array([turn])),
                                             gap_um, RESOLUTION))
    return rise, (edges[0][:-1] + edges[0][1:])/2, (edges[1][:-1] + edges[1][1:])/2


class Field:
    """Interpolated rise inside the carrier; points outside are clamped to the nearest valid cell centre."""
    def __init__(self, rise, xc, yc):
        cols, rows = np.isfinite(rise).any(0), np.isfinite(rise).any(1)
        self.x, self.y = xc[cols], yc[rows]
        self.f = RegularGridInterpolator((self.y, self.x), rise[np.ix_(rows, cols)])

    def __call__(self, points_mm):
        x = np.clip(points_mm[:, 0], self.x[0], self.x[-1])
        y = np.clip(points_mm[:, 1], self.y[0], self.y[-1])
        return self.f(np.c_[y, x])


def sample_points_um(problem, layout):
    """(n, 25, 2) points inside each die (5x5 at -0.4..0.4 of its rotated size)."""
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    grid = np.stack(np.meshgrid(POINTS, POINTS), -1).reshape(-1, 2)
    return layout.centre_um[:, None] + grid[None]*size[:, None]


def anchor_axes(problem, size_um, turn, anchors=ANCHORS):
    """Anchor centre coordinates (x, y) spanning the feasible centre range of a die of this size and turn."""
    w, h = size_um[::-1] if turn % 180 else size_um
    width, height = problem.carrier_um
    return np.linspace(w/2, width - w/2, anchors), np.linspace(h/2, height - h/2, anchors)


def anchor_table(problem, gap_um, pool, anchors=ANCHORS):
    """{(size, parity): (x anchors, y anchors, fields[iy][ix])} for every distinct powered die size."""
    keys = sorted({(tuple(problem.size_um[k]), t) for k in range(problem.count) if problem.power_w[k] for t in (0, 90)})
    jobs, slots = [], []
    for size, turn in keys:
        ax, ay = anchor_axes(problem, size, turn, anchors)
        for iy, y in enumerate(ay):
            for ix, x in enumerate(ax):
                jobs.append((problem, size, (x, y), turn, gap_um))
                slots.append((size, turn, iy, ix))
    table = {key: (*anchor_axes(problem, *key, anchors), [[None]*anchors for _ in range(anchors)]) for key in keys}
    for (size, turn, iy, ix), result in zip(slots, pool.map(lone_field, jobs)):
        table[(size, turn)][2][iy][ix] = Field(*result)
    return table


def bracket(axis, value):
    """[(index, weight)] of the two anchors around value (linear weights; one anchor if the axis is degenerate)."""
    if axis[-1] - axis[0] < 1e-6:
        return [(0, 1.0)]
    i = int(np.clip(np.searchsorted(axis, value) - 1, 0, len(axis) - 2))
    f = float(np.clip((value - axis[i])/(axis[i + 1] - axis[i]), 0, 1))
    return [(i, 1 - f), (i + 1, f)]


def anchor_peak_c(problem, layout, table):
    points = sample_points_um(problem, layout).reshape(-1, 2)
    rise = np.zeros(len(points))
    for j in np.flatnonzero(problem.power_w):
        turn = int(layout.rotation_deg[j] % 180)
        ax, ay, fields = table[(tuple(problem.size_um[j]), turn)]
        c = layout.centre_um[j]
        for iy, wy in bracket(ay, c[1]):
            for ix, wx in bracket(ax, c[0]):
                if wx*wy:
                    shifted = points + np.array([ax[ix], ay[iy]]) - c
                    rise += problem.power_w[j]*wx*wy*fields[iy][ix](to_package_mm(problem, shifted))
    return AMBIENT_C + float(rise.max())


def floor_peak_c(problem, layout, gap_um, pool):
    """Diagnostic: each powered die alone at its own centre, solved exactly, superposed."""
    points = to_package_mm(problem, sample_points_um(problem, layout).reshape(-1, 2))
    powered = np.flatnonzero(problem.power_w)
    jobs = [(problem, problem.size_um[j], layout.centre_um[j], int(layout.rotation_deg[j]), gap_um) for j in powered]
    rise = sum(problem.power_w[j]*Field(*f)(points) for j, f in zip(powered, pool.map(lone_field, jobs)))
    return AMBIENT_C + float(np.max(rise))


def fv_peak_c(args):
    problem, layout, gap_um = args
    _, rise, edges = solve(thermal_case_data(problem, layout, gap_um, RESOLUTION))
    return float(die_peaks_c(problem, layout, rise, edges).max())


def errors(pred, fv, n_front):
    err = pred - fv
    return dict(median_abs_k=float(np.median(np.abs(err))), p90_abs_k=float(np.percentile(np.abs(err), 90)),
                mean_bias_k=float(err.mean()), p90_debiased_k=float(np.percentile(np.abs(err - err.mean()), 90)),
                spearman_all=float(spearmanr(pred, fv)[0]), spearman_front=float(spearmanr(pred[:n_front], fv[:n_front])[0]))


def screen_case(name, problem, front, gap_um, rng, pool, anchors=ANCHORS):
    layouts = [front[i] for i in sorted(set(np.linspace(0, len(front) - 1, PER_FRONT).round().astype(int)))]
    n_front = len(layouts)
    layouts += [sample_legal(problem, gap_um, rng) for _ in range(RANDOM)]
    table = anchor_table(problem, gap_um, pool, anchors)
    fv = np.array(list(pool.map(fv_peak_c, [(problem, l, gap_um) for l in layouts])))
    anchor = np.array([anchor_peak_c(problem, l, table) for l in layouts])
    floor = np.array([floor_peak_c(problem, l, gap_um, pool) for l in layouts])
    row = dict(layouts=len(layouts), front_layouts=n_front, fv_range_front_k=float(np.ptp(fv[:n_front])),
               anchor=errors(anchor, fv, n_front), floor=errors(floor, fv, n_front),
               fv_c=fv.tolist(), anchor_c=anchor.tolist(), floor_c=floor.tolist())
    row['usable'] = row['anchor']['spearman_all'] >= 0.9 and row['anchor']['p90_debiased_k'] <= 2.0
    print(name, row['usable'], 'anchor overestimates', int((anchor >= fv).sum()), 'of', len(fv),
          {k: {m: round(v, 3) for m, v in row[k].items()} for k in ('anchor', 'floor')},
          'front range K', round(row['fv_range_front_k'], 2), flush=True)
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
    p.add_argument('--anchors', type=int, default=ANCHORS, help='anchors per axis (the frozen v2 screen uses 5)')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    rng = np.random.default_rng(args.seed)
    rows = {}
    with ProcessPoolExecutor(args.workers) as pool:
        for name, case, run in args.case:
            problem, front, gap = load_front(case, Path(run))
            rows[name] = screen_case(name, problem, front, gap, rng, pool, args.anchors)
    out = dict(plan='docs/thermal-kernel-screen-plan.md#v2', anchors=args.anchors, verdict=verdict(rows), cases=rows)
    args.output.write_text(json.dumps(out, indent=1) + '\n')
    print(out['verdict'])


if __name__ == '__main__':
    main()
