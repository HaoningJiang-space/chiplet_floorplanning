"""K-direction polygonal distance in the MILP: does it keep the Euclidean proxy's selection? (plan:
docs/polygon-distance-plan.md). Same layouts, stored FV and scores as tools/superpose_check.py; no layout FV."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import sample_legal
from chiplet_floorplanning.placement.proxy import ThermalProxy
from superpose_check import scores, validation_status
from thermal_kernel_screen import PER_FRONT, RANDOM, load_front

DIRECTIONS = (8, 16)


def verdict(rows):
    status = validation_status(rows)
    if status is not None:
        return status, []
    passing = [k for k in DIRECTIONS
               if all(r[f'polygon{k}']['front_budget_regret_k'] <= 0.6 and r[f'polygon{k}']['spearman_front'] >= 0.98
                      for r in rows.values())]
    return (f'adopt K={passing[0]}' if passing else 'not adopted'), passing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', nargs=3, action='append', required=True, metavar=('NAME', 'CASE_JSON', 'RUN_DIR'))
    p.add_argument('--stored', type=Path, default=Path('docs/evidence/physics-v2-proxy.json'))
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    stored = json.loads(args.stored.read_text())['cases']
    rng = np.random.default_rng(args.seed)
    rows = {}
    for name, case, run in args.case:
        problem, front, gap = load_front(case, Path(run))
        problem = replace(problem, limit_c=None)
        layouts = [front[i] for i in sorted(set(np.linspace(0, len(front) - 1, PER_FRONT).round().astype(int)))]
        n_front = len(layouts)
        layouts += [sample_legal(problem, gap, rng) for _ in range(RANDOM)]
        fv = np.array(stored[name]['fv_c'])
        proxy = ThermalProxy.calibrate(problem, gap)
        euclid = np.array([proxy.peak_c(problem, l) for l in layouts])
        row = dict(euclid_reproduction_max_diff_k=float(np.abs(euclid - np.array(stored[name]['proxy_c'])).max()),
                   euclid=scores(euclid, fv, n_front),
                   envelope=scores(np.array([proxy.envelope_value(problem, l, gap) for l in layouts]), fv, n_front))
        for k in DIRECTIONS:
            poly = np.array([proxy.polygon_value(problem, l, gap, k) for l in layouts])
            row[f'polygon{k}'] = scores(poly, fv, n_front)
            row[f'polygon{k}_minus_euclid_k'] = dict(min=float((poly - euclid).min()), max=float((poly - euclid).max()))
            row[f'polygon{k}_c'] = poly.tolist()
        rows[name] = row
        print(name, 'repro', round(row['euclid_reproduction_max_diff_k'], 6),
              {m: (round(row[m]['front_budget_regret_k'], 3), round(row[m]['spearman_front'], 3))
               for m in ('euclid', 'envelope', 'polygon8', 'polygon16')}, flush=True)
    result, passing = verdict(rows)
    print(result)
    args.output.write_text(json.dumps(dict(check='polygon', plan='docs/polygon-distance-plan.md', verdict=result,
                                           passing=passing, cases=rows), indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
