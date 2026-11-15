"""Per-die power allocation as a knob: does the coolest layout give the most sustained compute?
(plan: docs/coupling-search-plan.md)

Temperature is linear in die powers, so each layout's power-layer field is a sum of unit-power responses.
Compute dies take an activity x in [X_MIN, X_MAX] x nominal; other dies stay at nominal power.
Throughput = sum over compute dies of nominal_w * x**(1/3) (f ~ P**(1/3) under DVFS, capacity ~ nominal power),
maximised subject to every power-layer cell inside a die staying at or below that die's limit.
`uniform` scales every compute die by one common x (no per-die knob).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement import thermal
from workload_leverage import is_compute, kind

X_MIN, X_MAX = 0.2, 1.5
BREAKS = np.array([0.2, 0.3, 0.45, 0.6, 0.8, 1.0, 1.25, 1.5])
LIMITS_C = dict(primary=dict(logic=105., memory=95.), cool=dict(logic=95., memory=85.))
CAP_FACTOR = 1.25
MEANINGFUL, RESOLUTION = 0.03, 0.01


def responses(job):
    """Unit-power rise fields (dies, cells) on die cells only, plus each cell's die index."""
    case_path, centre, rotation, gap_um, resolution = job
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    layout = Layout(centre, rotation)
    fields, owner = [], None
    for i in range(problem.count):
        unit = replace(problem, power_w=np.eye(problem.count)[i])
        summary, rise, edges = thermal.solve(thermal.thermal_case_data(unit, layout, gap_um, resolution))
        if owner is None:
            owner = die_cells(problem, layout, edges)
        fields.append(rise.ravel()[owner >= 0])
    return np.array(fields), owner[owner >= 0]


def die_cells(problem, layout, edges):
    """Index of the die holding each power-layer cell centre (strictly inside), or -1."""
    width, height = (s/1000 for s in problem.carrier_um)
    offset = np.array([(thermal.PACKAGE_MM - width)/2, (thermal.PACKAGE_MM - height)/2])
    b = thermal.boxes(problem, layout)/1000 + np.r_[offset, offset]
    xc, yc = (edges[0][:-1] + edges[0][1:])/2, (edges[1][:-1] + edges[1][1:])/2
    owner = np.full((len(yc), len(xc)), -1)
    for k, (x0, y0, x1, y1) in enumerate(b):
        owner[np.ix_((yc > y0) & (yc < y1), (xc > x0) & (xc < x1))] = k
    return owner.ravel()


def limits(names, owner, which):
    memory = np.array([kind(n).startswith(('HBM', 'DRAM')) for n in names])
    return np.where(memory[owner], LIMITS_C[which]['memory'], LIMITS_C[which]['logic'])


def allocate(fields, owner, nominal, compute, limit_c, uniform=False):
    """Max sum nominal*x**(1/3) over compute dies; returns (throughput, x) or (None, None) if infeasible."""
    fixed = ~compute
    head = limit_c - thermal.AMBIENT_C - nominal[fixed] @ fields[fixed]  # room per cell, K
    a = (fields[compute]*nominal[compute][:, None]).T                    # K per unit activity
    c = np.flatnonzero(compute)
    if uniform:
        # one common x: the largest x with a.sum(1) * x <= head, within bounds
        load = a.sum(axis=1)
        if (head[load <= 0] < 0).any():
            return None, None
        x = min(X_MAX, np.min(head[load > 0]/load[load > 0]))
        if x < X_MIN:
            return None, None
        x = np.full(len(c), x)
        return float(nominal[c] @ x**(1/3)), x
    # x_i = X_MIN + sum_k s_ik, 0 <= s_ik <= step_k; concave objective so segments fill in order
    step, slope = np.diff(BREAKS), np.diff(BREAKS**(1/3))/np.diff(BREAKS)
    n, k = len(c), len(step)
    cost = -np.repeat(nominal[c], k)*np.tile(slope, n)
    a_ub = np.repeat(a, k, axis=1)
    b_ub = head - a.sum(axis=1)*X_MIN
    result = linprog(cost, A_ub=a_ub, b_ub=b_ub, bounds=list(zip(np.zeros(n*k), np.tile(step, n))), method='highs')
    if result.status == 2:
        return None, None
    if result.status != 0:
        raise RuntimeError(result.message)
    x = X_MIN + result.x.reshape(n, k).sum(axis=1)
    return float(nominal[c] @ x**(1/3)), x


def verdict(losses):
    """losses: per-case throughput loss of the coolest layout (None when not comparable)."""
    valid = [v for v in losses if v is not None]
    hit = sum(v >= MEANINGFUL for v in valid)
    return 'worthwhile' if hit >= 3 else 'degenerate' if all(v < RESOLUTION for v in valid) else 'uncertain'


def analyse(case_path, summary_path, layouts_path, workers):
    summary = json.loads(Path(summary_path).read_text())
    if sha256(Path(case_path).read_bytes()).hexdigest() != summary['case_sha256']:
        raise SystemExit(f'{case_path} is not the case the front was frozen on')
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    for p, i in zip(summary['front'], index):
        if abs(z['length_m'][i] - p['length_m']) > 1e-9 or abs(z['peak_c'][i] - p['peak_c']) > 1e-9:
            raise SystemExit(f'front point {i} does not match layouts.npz')
    jobs = [(str(case_path), z['centre_um'][i], z['rotation_deg'][i], summary['gap_um'], summary['fv_resolution'])
            for i in index]
    with ProcessPoolExecutor(workers) as pool:
        unit = list(pool.map(responses, jobs))
    nominal, compute = problem.power_w, is_compute(problem.names)
    peak = np.array([(nominal @ f).max() + thermal.AMBIENT_C for f, _ in unit])
    if np.abs(peak - [p['peak_c'] for p in summary['front']]).max() > 1e-6:
        raise SystemExit('superposed nominal peaks differ from the frozen front')
    length = np.array([p['length_m'] for p in summary['front']])
    within = np.flatnonzero(length <= CAP_FACTOR*length.min())
    coolest = int(within[np.argmin(peak[within])])
    out = dict(case=summary['case'], front_index=index, length_m=length.tolist(), peak_c=peak.tolist(),
               coolest=coolest, summary_sha256=sha256(Path(summary_path).read_bytes()).hexdigest(), limits={})
    for which in LIMITS_C:
        rows = []
        for f, owner in unit:
            lim = limits(problem.names, owner, which)
            t, x = allocate(f, owner, nominal, compute, lim)
            tu, _ = allocate(f, owner, nominal, compute, lim, uniform=True)
            rows.append(dict(throughput=t, uniform=tu, activity=None if x is None else x.tolist()))
        t = np.array([np.nan if r['throughput'] is None else r['throughput'] for r in rows])
        tu = np.array([np.nan if r['uniform'] is None else r['uniform'] for r in rows])
        feasible = within[np.isfinite(t[within])]
        best = int(feasible[np.argmax(t[feasible])]) if len(feasible) else None
        loss = None if best is None or not np.isfinite(t[coolest]) else float(1 - t[coolest]/t[best])
        knob = None if not (np.isfinite(t[coolest]) and np.isfinite(tu[coolest]) and tu[coolest] > 0) else \
            float(t[coolest]/tu[coolest] - 1)
        valid = within[np.isfinite(t[within])]
        rank = None
        if len(valid) > 2:
            r1, r2 = np.argsort(np.argsort(-peak[valid])), np.argsort(np.argsort(t[valid]))
            rank = float(np.corrcoef(r1, r2)[0, 1])
        out['limits'][which] = dict(rows=rows, best=best, loss=loss, knob_gain_at_coolest=knob, spearman_cool_vs_throughput=rank,
                                    nominal_throughput=float(nominal[compute] @ np.ones(compute.sum())))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=int, nargs='+', default=list(range(1, 11)))
    parser.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    parser.add_argument('--front-dir', type=Path, default=Path('results/front-gap0'))
    parser.add_argument('--summary-dir', type=Path, default=Path('docs/evidence/front-gap0'))
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    cases = []
    for n in args.cases:
        r = analyse(args.import_dir/f'Case{n}.json', args.summary_dir/f'case{n}-summary.json',
                    args.front_dir/f'case{n}'/'layouts.npz', args.workers)
        cases.append(r)
        print(r['case'], {w: (v['loss'], v['knob_gain_at_coolest'], v['spearman_cool_vs_throughput'])
                          for w, v in r['limits'].items()}, flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/coupling-search-plan.md',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), x_bounds=[X_MIN, X_MAX],
        limits_c=LIMITS_C, cap_factor=CAP_FACTOR, meaningful=MEANINGFUL, resolution=RESOLUTION,
        verdict={w: verdict([c['limits'][w]['loss'] for c in cases]) for w in LIMITS_C}, cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
