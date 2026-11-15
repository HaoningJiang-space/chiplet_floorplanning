"""Layouts for sustained power modes: minimise the worst over-limit temperature over every mode and die
(plan: docs/robust-modes-plan.md).

Modes = nominal plus every declared budget scenario (idle dies hand their power to the compute dies left
at full activity, each capped at boost x nominal). J(layout) = max over modes and dies of T_die - limit.
1. Cross-evaluation: frozen front plus the saved workload-search layouts, at each boost cap.
2. Direct search (SEARCH_CASES, PRIMARY_BOOST): lp_epsilon on J from the workload search's start set,
   budget and length cap; compared with the saved nominal-search winner N.
"""
import json
import time

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, pin_manhattan_um, sample_legal
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent
import frozen_front
from workload_leverage import budget_power, is_compute, kind, scenarios

BOOSTS, PRIMARY_BOOST = (1.0, 1.25, 1.5), 1.5
LIMIT_LOGIC_C, LIMIT_MEMORY_C = 105.0, 95.0
SEARCH_CASES = (3, 5, 9)
SEED, FV_SOLVES, BATCH, STARTS = 2026111401, 1000, 48, 48     # as the workload search (workload-search-v1.json, 9f56049)
CAP_FACTOR, MEANINGFUL_K, RESOLUTION_K = 1.25, 1.0, 0.3


def modes(problem, boost):
    """(mode names, power rows W): nominal first, then each budget scenario."""
    names, rows = ['nominal'], [problem.power_w]
    for s, activity in scenarios(problem.names).items():
        names.append(s)
        rows.append(budget_power(problem.power_w, activity, is_compute(problem.names), boost))
    return names, np.array(rows)


def limits(names):
    return np.array([LIMIT_MEMORY_C if kind(n).startswith(('HBM', 'DRAM')) else LIMIT_LOGIC_C for n in names])


def saved_layouts(saved):
    """Nominal-search winner and every saved scenario winner of one workload-search case."""
    out = {'nominal_best': Layout(np.array(saved['nominal']['centre_um']), np.array(saved['nominal']['rotation_deg']))}
    for name, t in saved['targets'].items():
        out[name] = Layout(np.array(t['centre_um']), np.array(t['rotation_deg']))
    return out


def scores(problem, layouts, gap_um, resolution, workers, boost):
    """J (K) and each die's hottest peak over the modes (degC)."""
    _, rows = modes(problem, boost)
    with Evaluator(problem, gap_um, resolution, workers, modes=(rows, limits(problem.names))) as evaluator:
        return evaluator.peaks_c(layouts), evaluator.die_peaks_c(layouts)


def compare(length, nominal, j, cap, n):
    """N (given) against the lowest-J candidate within the cap."""
    ok = np.flatnonzero(length <= cap + 1e-12)
    r = int(ok[np.argmin(j[ok])])
    return dict(nominal_best=n, robust_best=r, gain_k=float(j[n] - j[r]), j_nominal_best_k=float(j[n]),
                j_robust_best_k=float(j[r]), feasible_nominal_best=bool(j[n] <= 0), feasible_robust_best=bool(j[r] <= 0),
                reverse_cost_k=float(nominal[r] - nominal[n]), robust_length_m=float(length[r]))


def verdict(gains):
    hit = sum(g >= MEANINGFUL_K for g in gains)
    return 'worthwhile' if hit >= 2 else 'degenerate' if all(g < RESOLUTION_K for g in gains) else 'uncertain'


def analyse(n, case_path, summary_path, layouts_path, saved, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    cap = CAP_FACTOR*front.length_m.min()
    if abs(cap - saved['cap_m']) > 1e-9:
        raise SystemExit(f'{front.case}: cap differs from the workload search')
    extra = saved_layouts(saved)
    layouts = front.layouts + list(extra.values())
    length = np.array([pin_manhattan_um(problem, l).sum()/1e6 for l in layouts])
    with Evaluator(problem, gap, res, workers) as evaluator:
        nominal = evaluator.peaks_c(layouts)
    if np.abs(nominal[:len(front.layouts)] - front.peak_c).max() > 1e-6 or \
            abs(nominal[len(front.layouts)] - saved['nominal']['best_peak_c']) > 1e-6:
        raise SystemExit(f'{front.case}: nominal peaks differ from the frozen records')
    n_index = len(front.layouts)                               # the saved nominal-search winner
    out = dict(case=front.case, cap_m=cap, modes=modes(problem, PRIMARY_BOOST)[0],
               candidates=['front']*len(front.layouts) + list(extra), length_m=length.tolist(),
               nominal_c=nominal.tolist(), cross={})
    for boost in BOOSTS:
        j, _ = scores(problem, layouts, gap, res, workers, boost)
        out['cross'][str(boost)] = dict(compare(length, nominal, j, cap, n_index), j_k=j.tolist())
    if n in SEARCH_CASES:
        rng = np.random.default_rng(SEED)
        initial = [sample_legal(problem, gap, rng) for _ in range(STARTS)]
        initial += [length_descent(problem, sample_legal(problem, gap, rng), rng, gap) for _ in range(STARTS)]
        _, rows = modes(problem, PRIMARY_BOOST)
        started = time.perf_counter()
        with Evaluator(problem, gap, res, workers, modes=(rows, limits(problem.names))) as evaluator:
            run = Run(evaluator, FV_SOLVES)
            METHODS['lp_epsilon'](run, initial, np.random.default_rng([SEED, 10]), batch=BATCH, length_caps_m=[cap])
            s_length, s_j, _ = run.arrays()
            solves = evaluator.solves
        with Evaluator(problem, gap, res, workers) as evaluator:
            s_nominal = evaluator.peaks_c(run.layouts)
        j_all = np.r_[out['cross'][str(PRIMARY_BOOST)]['j_k'], s_j]
        row = compare(np.r_[length, s_length], np.r_[nominal, s_nominal], j_all, cap, n_index)
        best = (layouts + run.layouts)[row['robust_best']]
        modes_die = scores(problem, [best], gap, res, 1, PRIMARY_BOOST)[1][0]
        out['search'] = dict(row, solves=solves, stop=run.stop_reason,
                             robust_from='search' if row['robust_best'] >= len(layouts) else out['candidates'][row['robust_best']],
                             robust_die_peaks_c=modes_die.tolist(), centre_um=best.centre_um.tolist(),
                             rotation_deg=best.rotation_deg.tolist(), seconds=time.perf_counter() - started)
    print(front.case, {b: round(c['gain_k'], 2) for b, c in out['cross'].items()},
          out.get('search') and round(out['search']['gain_k'], 2), flush=True)
    return out


def main():
    p = frozen_front.parser(__doc__, cases=range(1, 11))
    p.add_argument('--workload-search', required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    saved = {c['case']: c for c in json.loads(open(args.workload_search).read())['cases']}
    cases = [analyse(n, *frozen_front.paths(args, n), saved[f'Case{n}'], args.workers)
             for n in args.cases if f'Case{n}' in saved]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/robust-modes-plan.md', boosts=BOOSTS, primary_boost=PRIMARY_BOOST,
        limits_c=dict(logic=LIMIT_LOGIC_C, memory=LIMIT_MEMORY_C), seed=SEED, fv_solves=FV_SOLVES,
        cap_factor=CAP_FACTOR, verdict=verdict([c['search']['gain_k'] for c in cases if 'search' in c]),
        cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
