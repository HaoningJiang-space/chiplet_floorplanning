"""Validation of the superposed single-die-field model on existing layouts (plan: docs/superposition-model-plan.md).

Rebuilds the layouts of physics check 2 exactly as tools/envelope_check.py does (front then random samples, one
rng, cases in order), predicts every layout's peak with SuperposedModel (one FV per distinct die size), and scores
it, the Euclidean proxy and the axial envelope against the stored FV peaks: error, debiased residual, Spearman,
budget-conditioned selection regret along the length-sorted front (front prefixes) and the random-subset regret.
The rotation fixture uses its stored FV pair. Gates are applied as frozen in the plan.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from chiplet_floorplanning.placement import Layout, Problem, sample_legal
from chiplet_floorplanning.placement.proxy import ThermalProxy
from chiplet_floorplanning.placement.superpose import SuperposedModel
from thermal_kernel_screen import PER_FRONT, RANDOM, load_front

ROTATION_FV = (76.52653, 78.15577)


def prefix_regret(pred, fv):
    """Max over k of FV(model pick among the first k) - min FV among the first k; ties pick the first."""
    return max(float(fv[int(np.argmin(pred[:k]))] - fv[:k].min()) for k in range(1, len(fv) + 1))


def scores(pred, fv, n_front):
    err = pred - fv
    return dict(max_abs_k=float(np.abs(err).max()), bias_k=float(err.mean()),
                debiased_max_k=float(np.abs(err - err.mean()).max()),
                spearman_all=float(spearmanr(pred, fv)[0]), spearman_front=float(spearmanr(pred[:n_front], fv[:n_front])[0]),
                spearman_random=float(spearmanr(pred[n_front:], fv[n_front:])[0]),
                front_budget_regret_k=prefix_regret(pred[:n_front], fv[:n_front]),
                random_regret_k=float(fv[n_front:][int(np.argmin(pred[n_front:]))] - fv[n_front:].min()))


def rotation_fixture():
    p = Problem('rot', ('a', 'b'), np.array([[20000., 4000.]]*2), np.array([100., 100.]), (50000., 40000.),
                np.zeros((0, 2), int), np.zeros((0, 2, 2)))
    model = SuperposedModel.calibrate(p)
    pred = [model.peak_c(p, Layout(np.array([[15000., 20000.], [28000., 20000.]]), np.array(r)))
            for r in ([90, 90], [0, 90])]
    return dict(model_c=pred, fv_c=list(ROTATION_FV), model_difference_k=pred[1] - pred[0],
                fv_difference_k=ROTATION_FV[1] - ROTATION_FV[0],
                difference_error_k=(pred[1] - pred[0]) - (ROTATION_FV[1] - ROTATION_FV[0]))


def verdict(rows, rotation):
    ok = all(r['superposed']['front_budget_regret_k'] <= 0.5 and r['superposed']['debiased_max_k'] <= 1.0
             and r['superposed']['spearman_front'] >= 0.98 for r in rows.values()) \
        and abs(rotation['difference_error_k']) <= 0.3
    bad = any(r['superposed']['front_budget_regret_k'] > 1.0 or r['superposed']['debiased_max_k'] > 2.0
              for r in rows.values())
    return 'adopt' if ok else 'reject' if bad else 'partial'


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
        envelope = np.array([proxy.envelope_value(problem, l, gap) for l in layouts])
        model = SuperposedModel.calibrate(problem)
        superposed = np.array([model.peak_c(problem, l) for l in layouts])
        rows[name] = dict(layouts=len(layouts), front_layouts=n_front, calibration_solves=model.solves,
                          euclid_reproduction_max_diff_k=float(np.abs(euclid - np.array(stored[name]['proxy_c'])).max()),
                          superposed=scores(superposed, fv, n_front), euclid=scores(euclid, fv, n_front),
                          envelope=scores(envelope, fv, n_front), superposed_c=superposed.tolist())
        s = rows[name]['superposed']
        print(name, 'repro', round(rows[name]['euclid_reproduction_max_diff_k'], 6),
              {k: round(v, 3) for k, v in s.items()}, '| euclid budget regret',
              round(rows[name]['euclid']['front_budget_regret_k'], 3), 'envelope',
              round(rows[name]['envelope']['front_budget_regret_k'], 3), flush=True)
    rotation = rotation_fixture()
    print('rotation', {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rotation.items()})
    result = verdict(rows, rotation)
    print(result)
    args.output.write_text(json.dumps(dict(check='superposed', plan='docs/superposition-model-plan.md', verdict=result,
                                           rotation=rotation, cases=rows), indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
