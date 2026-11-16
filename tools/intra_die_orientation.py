"""Thermal role of die orientation under non-uniform intra-die power: upper-bound screen
(plan: docs/intra-die-orientation-plan.md).

Compute dies split along their local x axis into two halves, one carrying a fraction f of the die power. A 180 degree
turn keeps the footprint, so the conduction matrix is shared by every orientation choice: the field is a sum of
per-half unit responses, solved once per layout.
"""
import json
import time

import numpy as np
from scipy.sparse.linalg import splu

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package, checked_solution, require_heat_path
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.placement import thermal_case_data
from chiplet_floorplanning.placement.thermal import AMBIENT_C, PROVENANCE
import frozen_front

COMPUTE = ('CPU1', 'CPU2', 'GPU')
SHARES = (0.8, 0.65)          # the verdict uses 0.8
LAYOUTS = 8


def is_compute(names):
    return np.array([n.rsplit('_', 1)[0] in COMPUTE for n in names])


def split_case(problem, layout, gap_um, resolution, powers):
    """Thermal case with every die split into local-x halves a (x < w/2) and b; powers is (n, 2) W."""
    data = thermal_case_data(problem, layout, gap_um, resolution)
    for chip, (pa, pb) in zip(data['chiplets'], powers):
        w, h = chip['size_mm']['width'], chip['size_mm']['height']
        chip['blocks'] = [dict(id='a', rect_mm=dict(x=0, y=0, width=w/2, height=h), power_w=float(pa), provenance=PROVENANCE),
                          dict(id='b', rect_mm=dict(x=w/2, y=0, width=w/2, height=h), power_w=float(pb), provenance=PROVENANCE)]
    return data


def half_responses(problem, layout, gap_um, resolution):
    """(n, 2, cells) power-layer rise (K) for 1 W in half a / b of each die, NaN outside dies."""
    n = problem.count
    out, lu = [], None
    for k in range(n):
        for half in range(2):
            p = np.zeros((n, 2))
            p[k, half] = 1.0
            case = parse_case(split_case(problem, layout, gap_um, resolution, p))
            power, _ = rasterize(case)
            a, b, g, _, ids, power_z = assemble_package(case, power)
            if lu is None:
                require_heat_path(a, g)
                lu = splu(a.tocsc(), permc_spec="MMD_AT_PLUS_A")
            theta = lu.solve(b)
            checked_solution(a, b, g, theta)
            layer = ids[power_z]
            out.append(np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan).ravel())
    return np.array(out).reshape(n, 2, -1)


def half_powers(problem, share, flipped):
    """(n, 2) W: compute dies put `share` of their power in half a, or half b when flipped; others are uniform."""
    hot = np.where(is_compute(problem.names), share, 0.5)
    hot = np.where(flipped, 1 - hot, hot)
    return problem.power_w[:, None]*np.c_[hot, 1 - hot]


def peak_c(responses, powers):
    return float(np.nanmax(np.einsum('kh,khc->c', powers, responses)) + AMBIENT_C)


def orient(problem, responses, share, sign):
    """Greedy flips of compute dies from the given orientation; sign=+1 minimises the peak, -1 maximises it."""
    flipped = np.zeros(problem.count, bool)
    best = sign*peak_c(responses, half_powers(problem, share, flipped))
    improved = True
    while improved:
        improved = False
        for k in np.flatnonzero(is_compute(problem.names)):
            flipped[k] = ~flipped[k]
            value = sign*peak_c(responses, half_powers(problem, share, flipped))
            if value < best - 1e-9:
                best, improved = value, True
            else:
                flipped[k] = ~flipped[k]
    return sign*best, flipped


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1]) if len(a) > 2 else None


def analyse(case_path, summary_path, layouts_path):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    started = time.perf_counter()
    order = np.argsort(front.length_m)
    picks = sorted({int(order[i]) for i in np.linspace(0, len(order) - 1, LAYOUTS).round().astype(int)})
    rows = []
    for i in picks:
        responses = half_responses(problem, front.layouts[i], gap, res)
        row = dict(front_index=i, length_m=float(front.length_m[i]), frozen_peak_c=float(front.peak_c[i]),
                   uniform_c=peak_c(responses, half_powers(problem, 0.5, np.zeros(problem.count, bool))))
        for share in SHARES:
            low, flips = orient(problem, responses, share, +1)
            high, _ = orient(problem, responses, share, -1)
            row[str(share)] = dict(original_c=peak_c(responses, half_powers(problem, share, np.zeros(problem.count, bool))),
                                   best_c=low, worst_c=high, best_flips=np.flatnonzero(flips).tolist())
        rows.append(row)
    out = dict(case=front.case, compute_dies=int(is_compute(problem.names).sum()), layouts=rows, by_share={})
    uniform = np.array([r['uniform_c'] for r in rows])
    for share in SHARES:
        s = str(share)
        best = np.array([r[s]['best_c'] for r in rows])
        out['by_share'][s] = dict(
            orientation_gain_k=float(max(r[s]['original_c'] - r[s]['best_c'] for r in rows)),
            orientation_range_k=float(max(r[s]['worst_c'] - r[s]['best_c'] for r in rows)),
            layout_regret_k=float(best[np.argmin(uniform)] - best.min()),
            spearman=spearman(uniform, best))
    print(front.case, {s: {k: v if v is None else round(v, 2) for k, v in d.items()} for s, d in out['by_share'].items()},
          f'{time.perf_counter() - started:.0f}s', flush=True)
    return out


def verdict(cases, share='0.8'):
    d = [c['by_share'][share] for c in cases]
    big = sum(x['orientation_gain_k'] >= 3 or x['layout_regret_k'] >= 2 for x in d)
    if big >= 3:
        return 'calibrate'
    if all(x['orientation_gain_k'] < 1 and x['layout_regret_k'] < 1 for x in d):
        return 'stop'
    return 'uncertain'


def _job(args):
    return analyse(*args)


def main():
    from concurrent.futures import ProcessPoolExecutor
    args = frozen_front.arguments(__doc__)
    with ProcessPoolExecutor(min(args.workers, len(args.cases))) as pool:
        cases = list(pool.map(_job, [frozen_front.paths(args, n) for n in args.cases]))
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/intra-die-orientation-plan.md', shares=SHARES, layouts_per_case=LAYOUTS,
        verdict=verdict(cases), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
