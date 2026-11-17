"""First-principles checks of lateral thermal coupling (plan: docs/physics-checks-plan.md).

decay: mutual heating g(r) of a 1 W, 5 x 5 mm source seen by a 1 x 1 mm unpowered die at centre distance r, fitted
       with the far field of K0(r / lambda) and compared with lambda = sqrt(k t / h) of the spreader and sink.
proxy: peak ~ 45 + max_i [P_i s_i + sum_j P_j g(r_ij)] against FV on front and random layouts.
area:  predicted rise of mutual heating when the carrier shrinks to 0.85x against the measured area screen.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import k0
from scipy.stats import spearmanr

from chiplet_floorplanning.placement import Problem, sample_legal
from chiplet_floorplanning.placement.proxy import R_MM, decay, fit_lambda, g_model, self_heating
from chiplet_floorplanning.placement.thermal import AMBIENT_C
from thermal_kernel_screen import PER_FRONT, RANDOM, fv_peak_c, load_front

H_SWEEP = (1500.0, 1/(.1*.06**2), 5000.0, 15000.0, 50000.0)
KT_W_K = 400*0.001 + 400*0.0069           # spreader (1 mm Cu) + sink (6.9 mm Cu)


def lambda_theory_mm(h):
    return math.sqrt(KT_W_K/h)*1000


def fit_lambda_k0(r_mm, g):
    """Control without the far-field approximation: least squares of ln g = ln a + ln K0(r / lambda)."""
    keep = g > 0.01*g[0]
    (lam, ln_a), _ = curve_fit(lambda r, lam, ln_a: ln_a + np.log(k0(r/lam)), r_mm[keep], np.log(g[keep]),
                               p0=(fit_lambda(r_mm, g)[0], 0.0), bounds=([1.0, -50.0], [500.0, 50.0]))
    return lam, ln_a


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
        lam_k0, _ = fit_lambda_k0(R_MM, g)
        rows.append(dict(h=h, g_k_w=g.tolist(), lambda_fit_mm=lam, c=c, lambda_k0_fit_mm=lam_k0,
                         lambda_theory_mm=lambda_theory_mm(h)))
        print(f'h {h:.0f}: lambda fit {lam:.1f} mm (exact-K0 control {lam_k0:.1f}), theory {lambda_theory_mm(h):.1f} mm',
              flush=True)
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
            s, _ = self_heating(problem, gap)
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


def predicted_area_rise(problem, lam, c, factor):
    """factor is an AREA factor; the old area screen scaled each side, so its 0.85 is an area factor of 0.7225."""
    n, area = problem.count, problem.carrier_um[0]*problem.carrier_um[1]/1e6
    spacing = lambda f: math.sqrt(f*area/n)
    return problem.power_w.sum()/n*4*float(g_model(np.array(spacing(factor)), lam, c) - g_model(np.array(spacing(1.0)), lam, c))


def cmd_area(args):
    lam, c = fit_lambda(R_MM, decay(H_SWEEP[1]))
    screen = json.loads(args.screen.read_text())['cases']
    rows = {}
    for name, row in screen.items():
        problem = Problem.from_imported(json.loads((args.import_dir/f'{name}.json').read_text()))
        # Revision: side scale 0.85 -> area factor 0.7225; "no layout found" is unknown, not most sensitive.
        rows[name] = dict(linear_scale=0.85, area_factor=0.85**2,
                          predicted_k=predicted_area_rise(problem, lam, c, 0.85**2), measured_k=row['dT_area_k'],
                          unknown=bool(row['infeasible_0p85']))
    found = [r for r in rows.values() if not r['unknown']]
    rho = float(spearmanr([r['predicted_k'] for r in found], [r['measured_k'] for r in found])[0])
    within3 = sum(1/3 <= r['predicted_k']/r['measured_k'] <= 3 for r in found if r['measured_k'] > 0)
    result = 'holds' if rho >= 0.7 else 'fails' if rho < 0.3 else 'partial'
    for name, r in rows.items():
        print(name, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
    print(result, round(rho, 3), 'within 3x:', within3)
    args.output.write_text(json.dumps(dict(check='area', plan='docs/sizing-plan-revisions.md section 6',
                                           verdict=result, spearman=rho, within_3x=within3, cases_ranked=len(found),
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
