"""Split each front layout's hottest-die rise into self heating and mutual heating (air sink, nominal power).
Run from the repository root: PYTHONPATH=src:tools python tools/self_mutual_split.py (eex005; writes results/)."""
from concurrent.futures import ProcessPoolExecutor
import json
import numpy as np

import frozen_front
from boost_headroom import die_rise_matrix


def split(job):
    problem, layout, gap, res = job
    rise = die_rise_matrix(problem, layout, gap, res)
    p = problem.power_w
    total = [(p @ r).max() for r in rise]
    k = int(np.argmax(total))
    cell = int(np.argmax(p @ rise[k]))
    self_k = float(p[k]*rise[k][k, cell])
    return dict(hot_die=problem.names[k], rise_k=float(total[k]), self_k=self_k, mutual_k=float(total[k] - self_k))


def main():
    out = {}
    for n in range(1, 11):
        f = frozen_front.load(f'results/physical-calibration/atplace-import-v1/Case{n}.json',
                              f'docs/evidence/front-gap0/case{n}-summary.json', f'results/front-gap0/case{n}/layouts.npz')
        with ProcessPoolExecutor(10) as pool:
            rows = list(pool.map(split, [(f.problem, l, f.gap_um, f.resolution) for l in f.layouts]))
        if np.abs(np.array([r['rise_k'] for r in rows]) + 45 - f.peak_c).max() > 1e-6:
            raise SystemExit(f'Case{n}: superposed peak differs from the front')
        cap = 1.25*f.length_m.min()
        ok = np.flatnonzero(f.length_m <= cap + 1e-12)
        cool, short = int(ok[np.argmin(f.peak_c[ok])]), int(np.argmin(f.length_m))
        frac = np.array([r['mutual_k']/r['rise_k'] for r in rows])
        out[f'Case{n}'] = dict(rows=rows, length_m=f.length_m.tolist(), coolest=cool, shortest=short)
        print(f'Case{n}', 'mutual share min/median/max', np.round([frac.min(), np.median(frac), frac.max()], 3),
              'shortest', {k: round(v, 1) if isinstance(v, float) else v for k, v in rows[short].items()},
              'coolest', {k: round(v, 1) if isinstance(v, float) else v for k, v in rows[cool].items()}, flush=True)
    json.dump(out, open('results/self-mutual-v1.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
