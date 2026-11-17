"""First-principles checks of lateral thermal coupling (plan: docs/physics-checks-plan.md).

decay: mutual heating g(r) of a 1 W, 5 x 5 mm source seen by a 1 x 1 mm unpowered die at centre distance r, fitted
       with the far field of K0(r / lambda) and compared with lambda = sqrt(k t / h) of the spreader and sink.
proxy: peak ~ 45 + max_i [P_i s_i + sum_j P_j g(r_ij)] against FV on front and random layouts.
area:  predicted rise of mutual heating when the carrier shrinks to 0.85x against the measured area screen.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from chiplet_floorplanning.placement import Layout, Problem, sample_legal, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import AMBIENT_C, die_peaks_c
from thermal_kernel_screen import PER_FRONT, RANDOM, fv_peak_c, load_front

R_MM = np.array([6., 8., 12., 16., 24., 32., 40., 50., 60.])
H_SWEEP = (1500.0, 1/(.1*.06**2), 5000.0, 15000.0, 50000.0)
KT_W_K = 400*0.001 + 400*0.0069           # spreader (1 mm Cu) + sink (6.9 mm Cu)
RESOLUTION = 64


def lambda_theory_mm(h):
    return math.sqrt(KT_W_K/h)*1000


def rise_c(problem, layout, gap_um=0.0):
    _, rise, edges = solve(thermal_case_data(problem, layout, gap_um, RESOLUTION))
    return die_peaks_c(problem, layout, rise, edges) - AMBIENT_C


def decay(h):
    """Mutual heating g(r) (K/W) at R_MM in a 90 x 30 mm carrier with sink-top h."""
    problem = Problem('decay', ('src', 'obs'), np.array([[5000., 5000.], [1000., 1000.]]), np.array([1., 0.]),
                      (90000., 30000.), np.zeros((0, 2), int), np.zeros((0, 2, 2)), top_h_w_m2k=h)
    return np.array([rise_c(problem, Layout(np.array([[10000., 15000.], [10000. + r*1000, 15000.]]),
                                            np.zeros(2, int)))[1] for r in R_MM])


def fit_lambda(r_mm, g):
    """(lambda mm, c) of ln g + 0.5 ln r = c - r / lambda over the points above 1% of the nearest one."""
    keep = g > 0.01*g[0]
    slope, c = np.polyfit(r_mm[keep], np.log(g[keep]) + 0.5*np.log(r_mm[keep]), 1)
    return -1/slope, c


def g_model(r_mm, lam, c):
    r = np.maximum(r_mm, 3.0)               # adjacent dies: keep the far-field form finite
    return np.exp(c - r/lam)/np.sqrt(r)


def decay_verdict(rows):
    lam_fit = np.array([r['lambda_fit_mm'] for r in rows])
    ratio_ok = sum(1/1.5 <= r['lambda_fit_mm']/r['lambda_theory_mm'] <= 1.5 for r in rows)
    slope = np.polyfit(np.log([r['h'] for r in rows]), np.log(lam_fit), 1)[0]
    monotone = bool(np.all(np.diff(lam_fit) < 0))
    if ratio_ok >= 4 and monotone and -0.65 <= slope <= -0.35:
        return 'holds', ratio_ok, slope
    if ratio_ok < 2 or not -0.8 <= slope <= -0.2:
        return 'fails', ratio_ok, slope
    return 'partial', ratio_ok, slope


def proxy_peak_c(problem, layout, self_k_w, lam, c):
    d = np.linalg.norm(layout.centre_um[:, None] - layout.centre_um[None], axis=2)/1000
    mutual = g_model(d, lam, c)*problem.power_w[None]
    np.fill_diagonal(mutual, 0.0)
    return AMBIENT_C + float((problem.power_w*self_k_w + mutual.sum(axis=1)).max())


def self_heating(problem, gap_um):
    """Per die: peak rise (K/W) of that die alone, 1 W, at the carrier centre (one solve per distinct size)."""
    by_size = {}
    for k in range(problem.count):
        key = tuple(problem.size_um[k])
        if key not in by_size:
            alone = Problem(problem.name, ('die',), problem.size_um[k:k + 1], np.ones(1), problem.carrier_um,
                            np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
            by_size[key] = rise_c(alone, Layout(np.array(problem.carrier_um)[None]/2, np.zeros(1, int)), gap_um)[0]
    return np.array([by_size[tuple(s)] for s in problem.size_um])


def proxy_verdict(rows):
    rho = [r['spearman_all'] for r in rows.values()]
    if sum(x >= 0.8 for x in rho) >= 5:
        return 'usable'
    return 'not_usable' if sum(x < 0.6 for x in rho) >= 4 else 'partial'


def cmd_decay(args):
    rows = []
    for h in H_SWEEP:
        g = decay(h)
        lam, c = fit_lambda(R_MM, g)
        rows.append(dict(h=h, g_k_w=g.tolist(), lambda_fit_mm=lam, c=c, lambda_theory_mm=lambda_theory_mm(h)))
        print(f'h {h:.0f}: lambda fit {lam:.1f} mm, theory {lambda_theory_mm(h):.1f} mm', flush=True)
    result, ok, slope = decay_verdict(rows)
    print(result, ok, round(slope, 3))
    args.output.write_text(json.dumps(dict(check='decay', verdict=result, ratio_ok=ok, slope=slope, rows=rows),
                                      indent=1, default=float) + '\n')


def cmd_proxy(args):
    rng = np.random.default_rng(args.seed)
    rows = {}
    with ProcessPoolExecutor(args.workers) as pool:
        for name, case, run in args.case:
            problem, front, gap = load_front(case, Path(run))
            h = problem.top_h_w_m2k or H_SWEEP[1]
            lam, c = fit_lambda(R_MM, decay(h))
            s = self_heating(problem, gap)
            layouts = [front[i] for i in sorted(set(np.linspace(0, len(front) - 1, PER_FRONT).round().astype(int)))]
            n_front = len(layouts)
            layouts += [sample_legal(problem, gap, rng) for _ in range(RANDOM)]
            fv = np.array(list(pool.map(fv_peak_c, [(problem, l, gap) for l in layouts])))
            proxy = np.array([proxy_peak_c(problem, l, s, lam, c) for l in layouts])
            rows[name] = dict(lambda_mm=lam, spearman_all=float(spearmanr(proxy, fv)[0]),
                              spearman_front=float(spearmanr(proxy[:n_front], fv[:n_front])[0]),
                              bias_k=float((proxy - fv).mean()), fv_c=fv.tolist(), proxy_c=proxy.tolist())
            print(name, {k: round(v, 3) for k, v in rows[name].items() if not isinstance(v, list)}, flush=True)
    result = proxy_verdict(rows)
    print(result)
    args.output.write_text(json.dumps(dict(check='proxy', verdict=result, cases=rows), indent=1, default=float) + '\n')


def predicted_area_rise(problem, lam, c, factor=0.85):
    n, area = problem.count, problem.carrier_um[0]*problem.carrier_um[1]/1e6
    spacing = lambda f: math.sqrt(f*area/n)
    return problem.power_w.sum()/n*4*float(g_model(np.array(spacing(factor)), lam, c) - g_model(np.array(spacing(1.0)), lam, c))


def cmd_area(args):
    lam, c = fit_lambda(R_MM, decay(H_SWEEP[1]))
    screen = json.loads(args.screen.read_text())['cases']
    rows = {}
    for name, row in screen.items():
        problem = Problem.from_imported(json.loads((args.import_dir/f'{name}.json').read_text()))
        rows[name] = dict(predicted_k=predicted_area_rise(problem, lam, c), measured_k=row['dT_area_k'],
                          infeasible=row['infeasible_0p85'])
    measured = [math.inf if r['infeasible'] else r['measured_k'] for r in rows.values()]
    rho = float(spearmanr([r['predicted_k'] for r in rows.values()], measured)[0])
    within3 = sum(1/3 <= r['predicted_k']/r['measured_k'] <= 3 for r in rows.values()
                  if not r['infeasible'] and r['measured_k'] > 0)
    result = 'holds' if rho >= 0.7 else 'fails' if rho < 0.3 else 'partial'
    for name, r in rows.items():
        print(name, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
    print(result, round(rho, 3), 'within 3x:', within3)
    args.output.write_text(json.dumps(dict(check='area', verdict=result, spearman=rho, within_3x=within3,
                                           lambda_mm=lam, rows=rows), indent=1, default=float) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('decay', 'proxy', 'area'))
    p.add_argument('--case', nargs=3, action='append', metavar=('NAME', 'CASE_JSON', 'RUN_DIR'))
    p.add_argument('--screen', type=Path, help='area: screens/area-v1.json')
    p.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    {'decay': cmd_decay, 'proxy': cmd_proxy, 'area': cmd_area}[args.command](args)


if __name__ == '__main__':
    main()
