"""How much sustained power shifting can each layout carry? (plan: docs/boost-headroom-plan.md)

The package power of each case is scaled by one factor s so that the full-load baseline L (the candidate
within the length cap with the lowest full-load overshoot) keeps MARGIN_K below its die limits. For every
candidate that also meets the limits at full load, b_max = the largest boost cap (robust_modes.modes) under
which every mode keeps every die within its limit, found by bisection. Temperatures superpose: each layout
solves one 1 W response per die, and every (s, boost, mode) power row is a matrix product.
"""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, pin_manhattan_um
from chiplet_floorplanning.placement.thermal import AMBIENT_C, die_cells, power_layer_responses
import frozen_front
from robust_modes import limits, modes, saved_layouts

MARGINS_K, PRIMARY_MARGIN_K = (2.0, 5.0, 10.0), 5.0
B_HIGH, B_TOL = 2.0, 1e-4
CAP_FACTOR, MEANINGFUL_B, RESOLUTION_B = 1.25, 0.1, 0.02


def die_rise_matrix(problem, layout, gap_um, resolution):
    """Per die, its cells' rise (K) per 1 W in every die: list of (n_dies, cells) arrays."""
    n = len(problem.names)
    fields, edges = power_layer_responses(problem, layout, gap_um, np.eye(n), resolution)
    return [fields[:, inside[0], inside[1]].reshape(n, -1) for inside in die_cells(problem, layout, edges)]


def worst_overshoot(rise, rows, limit):
    """max over power rows and dies of T - limit (K)."""
    return max(float(((rows @ r).max(1) + AMBIENT_C - limit[k]).max()) for k, r in enumerate(rise))


def b_max(rise, problem, scale, limit):
    """Largest boost cap in [1, B_HIGH] keeping every mode within the limits (temperature is nondecreasing
    in the cap); None if the layout already fails at full load, B_HIGH if it never fails."""
    scaled = replace(problem, power_w=scale*problem.power_w)
    ok = lambda b: worst_overshoot(rise, modes(scaled, b)[1], limit) <= 0
    if not ok(1.0):
        return None
    if ok(B_HIGH):
        return B_HIGH
    lo, hi = 1.0, B_HIGH
    while hi - lo > B_TOL:
        mid = (lo + hi)/2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def layout_headroom(job):
    problem, layout, gap_um, resolution, scales = job
    rise = die_rise_matrix(problem, layout, gap_um, resolution)
    limit = limits(problem.names)
    return [b_max(rise, problem, s, limit) for s in scales]


def scale_for_margin(die_rise_k, limit, margin_k):
    """Power scale at which this layout's hottest die sits margin_k below its limit at full load."""
    return float(((limit - margin_k - AMBIENT_C)/die_rise_k).min())


def compare(length, cap, full_scale, b, baseline):
    """Baseline L against the candidate with the largest b_max within the cap."""
    ok = [i for i in np.flatnonzero(length <= cap + 1e-12) if b[i] is not None]
    r = max(ok, key=lambda i: (b[i], full_scale[i]))
    return dict(baseline=int(baseline), robust_best=int(r), b_baseline=b[baseline], b_robust_best=b[r],
                gain_b=b[r] - b[baseline], censored=b[r] >= B_HIGH,
                # how much hotter R runs at full load, as the power scale at which it would hit its limit
                full_load_scale_ratio=full_scale[r]/full_scale[baseline], robust_length_m=float(length[r]),
                feasible_candidates=len(ok))


def verdict(gains):
    if not gains:
        return 'no_data'
    hit = sum(g >= MEANINGFUL_B for g in gains)
    return 'worthwhile' if hit >= 3 else 'degenerate' if all(g < RESOLUTION_B for g in gains) else 'uncertain'


def analyse(case_path, summary_path, layouts_path, saved, robust, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    cap = CAP_FACTOR*front.length_m.min()
    extra = saved_layouts(saved)
    if robust and 'search' in robust:
        s = robust['search']
        extra['robust_search_best'] = Layout(np.array(s['centre_um']), np.array(s['rotation_deg']))
        extra['limit_baseline_search_best'] = Layout(np.array(s['baseline_centre_um']), np.array(s['baseline_rotation_deg']))
    layouts = front.layouts + list(extra.values())
    names = ['front']*len(front.layouts) + list(extra)
    length = np.array([pin_manhattan_um(problem, l).sum()/1e6 for l in layouts])
    limit = limits(problem.names)
    with Evaluator(problem, gap, res, workers) as evaluator:
        nominal = evaluator.peaks_c(layouts)
        die = evaluator.die_peaks_c(layouts)
    if np.abs(nominal[:len(front.layouts)] - front.peak_c).max() > 1e-6:
        raise SystemExit(f'{front.case}: nominal peaks differ from the frozen front')
    # Scale at which each layout would just meet its limits at full load; L has the largest within the cap.
    full_scale = np.array([scale_for_margin(d - AMBIENT_C, limit, 0.0) for d in die])
    ok = np.flatnonzero(length <= cap + 1e-12)
    baseline = int(ok[np.argmax(full_scale[ok])])
    scales = [scale_for_margin(die[baseline] - AMBIENT_C, limit, m) for m in MARGINS_K]
    jobs = [(problem, l, gap, res, scales) for l in layouts]
    with ProcessPoolExecutor(workers) as pool:
        b = list(pool.map(layout_headroom, jobs))
    out = dict(case=front.case, cap_m=cap, candidates=names, length_m=length.tolist(), full_scale=full_scale.tolist(),
               baseline=baseline, baseline_from=names[baseline], scales=dict(zip(map(str, MARGINS_K), scales)),
               b_max={str(m): [x[i] for x in b] for i, m in enumerate(MARGINS_K)}, rows={})
    for i, m in enumerate(MARGINS_K):
        row = compare(length, cap, full_scale, [x[i] for x in b], baseline)
        out['rows'][str(m)] = dict(row, robust_from=names[row['robust_best']])
    print(front.case, {m: (round(v['b_baseline'], 3), round(v['b_robust_best'], 3), v['robust_from'])
                       for m, v in out['rows'].items()}, flush=True)
    return out


def main():
    p = frozen_front.parser(__doc__, cases=(1, 2, 3, 4, 5, 6, 9, 10))
    p.add_argument('--workload-search', required=True)
    p.add_argument('--robust-modes', required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    saved = {c['case']: c for c in json.loads(open(args.workload_search).read())['cases']}
    robust = {c['case']: c for c in json.loads(open(args.robust_modes).read())['cases']}
    cases = [analyse(*frozen_front.paths(args, n), saved[f'Case{n}'], robust.get(f'Case{n}'), args.workers)
             for n in args.cases]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/boost-headroom-plan.md', margins_k=MARGINS_K,
        primary_margin_k=PRIMARY_MARGIN_K, b_high=B_HIGH, cap_factor=CAP_FACTOR,
        verdict=verdict([c['rows'][str(PRIMARY_MARGIN_K)]['gain_b'] for c in cases]),
        margin_verdicts={str(m): verdict([c['rows'][str(m)]['gain_b'] for c in cases]) for m in MARGINS_K},
        cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
