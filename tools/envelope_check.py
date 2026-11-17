"""Does the MILP's axial tangent envelope keep the ranking that validated the Euclidean proxy? (no new layout FV)

Rebuilds the exact layouts of physics check 2 (docs/evidence/physics-v2-proxy.json: per case the 20 front layouts of
the frozen run, then 20 legal samples from one rng with the same seed, cases in the same order), recalibrates the
proxy (about ten FV per case, deterministic), and checks that the recomputed Euclidean proxy matches the stored one.
It then scores the envelope that proxy_space actually optimises (ThermalProxy.envelope_value) against the stored FV
peaks: Spearman, the regret of the layout each predictor would pick (FV of the pick minus the sample's FV best), and
the error range. Absolute peaks throughout (limits dropped), as in check 2.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from chiplet_floorplanning.placement import sample_legal
from chiplet_floorplanning.placement.proxy import ThermalProxy
from thermal_kernel_screen import PER_FRONT, RANDOM, load_front


def score(pred, fv):
    pick = int(np.argmin(pred))
    return dict(spearman=float(spearmanr(pred, fv)[0]), regret_k=float(fv[pick] - fv.min()),
                bias_k=float((pred - fv).mean()), max_abs_k=float(np.abs(pred - fv).max()))


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
        model = ThermalProxy.calibrate(problem, gap)
        fv = np.array(stored[name]['fv_c'])
        euclid = np.array([model.peak_c(problem, l) for l in layouts])
        envelope = np.array([model.envelope_value(problem, l, gap) for l in layouts])
        rows[name] = dict(
            layouts=len(layouts), front_layouts=n_front,
            euclid_reproduction_max_diff_k=float(np.abs(euclid - np.array(stored[name]['proxy_c'])).max()),
            euclid=score(euclid, fv), envelope=score(envelope, fv),
            envelope_front=score(envelope[:n_front], fv[:n_front]),
            envelope_random=score(envelope[n_front:], fv[n_front:]),
            envelope_minus_euclid_k=dict(min=float((envelope - euclid).min()), max=float((envelope - euclid).max())),
            envelope_c=envelope.tolist())
        r = rows[name]
        print(name, 'repro', round(r['euclid_reproduction_max_diff_k'], 6),
              'euclid', {k: round(v, 3) for k, v in r['euclid'].items()},
              'envelope', {k: round(v, 3) for k, v in r['envelope'].items()}, flush=True)
    args.output.write_text(json.dumps(dict(check='envelope', stored=str(args.stored), seed=args.seed, cases=rows),
                                      indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
