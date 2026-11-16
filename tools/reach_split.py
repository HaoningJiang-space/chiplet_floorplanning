"""Reach cost split by link class (plan: docs/reach-split-plan.md).

The v3 reach search (tools/reach_cost.py) with the 2 mm reach applied to one class of links only: compute-compute
or compute-memory; every other link is unconstrained. The cost is taken against the v3 reference, and each chosen
layout reports how far its memory and compute dies run over their declared limits.
"""
import json
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout
import frozen_front
from reach_cost import SEED, link_pairs, search, shared_starts

REACH_MM = 2.0
CASES = (1, 3, 4, 6, 9)
COMPUTE, MEMORY = ('CPU1', 'CPU2', 'GPU'), ('HBM', 'DRAM')
LIMIT_C = dict(compute=105.0, memory=95.0)


def kinds(problem):
    return np.array(['compute' if n.rsplit('_', 1)[0] in COMPUTE else 'memory' if n.rsplit('_', 1)[0] in MEMORY
                     else 'other' for n in problem.names])


def link_classes(problem, pairs):
    """{'compute-compute': pairs, 'compute-memory': pairs}; other links are never constrained."""
    k = kinds(problem)[pairs]
    both = (k == 'compute').all(1)
    mixed = ((k == 'compute') & (k[:, ::-1] == 'memory')).any(1)
    return {'compute-compute': pairs[both], 'compute-memory': pairs[mixed]}


def overshoot(problem, die_peaks_c):
    """Worst die temperature over its limit (K) for compute and memory dies."""
    k = kinds(problem)
    return {kind: float((die_peaks_c[k == kind] - limit).max()) for kind, limit in LIMIT_C.items()}


def memory_bound(o):
    return o['memory'] > o['compute']


def analyse(case_path, summary_path, layouts_path, workers, v3):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    pairs, _ = link_pairs(problem)
    initial = shared_starts(front)
    started = time.perf_counter()
    unlimited = v3['search'][str(1e9)]
    reference = Layout(np.array(unlimited['centre_um']), np.array(unlimited['rotation_deg']))
    with Evaluator(problem, gap, res) as evaluator:
        out = dict(case=front.case, reference_coolest_c=v3['reference_coolest_c'],
                   reference_overshoot_k=overshoot(problem, evaluator.die_peaks_c([reference])[0]), classes={})
        for name, links in link_classes(problem, pairs).items():
            found = search(problem, initial, REACH_MM, gap, res, workers, links)
            row = dict(links=links.tolist(), feasible=found['feasible'], least_over_reach_mm=found['least_over_reach_mm'])
            if found['feasible']:
                layout = Layout(np.array(found['centre_um']), np.array(found['rotation_deg']))
                row.update(cost_k=found['peak_c'] - v3['reference_coolest_c'], peak_c=found['peak_c'],
                           overshoot_k=overshoot(problem, evaluator.die_peaks_c([layout])[0]),
                           centre_um=found['centre_um'], rotation_deg=found['rotation_deg'])
            out['classes'][name] = row
    print(front.case, {n: r.get('cost_k') and round(r['cost_k'], 2) for n, r in out['classes'].items()},
          f'{time.perf_counter() - started:.0f}s', flush=True)
    return out


def verdict(cases):
    def cost(row):
        return row['cost_k'] if row['feasible'] else np.inf

    a = 0
    for c in cases:
        cc, cm = cost(c['classes']['compute-compute']), cost(c['classes']['compute-memory'])
        a += bool(cc >= 5 and np.isfinite(cm) and cc >= 2*max(cm, .5))    # both not found: not attributable
    b = 0
    for c in cases:
        row = c['classes']['compute-memory']
        b += bool(row['feasible'] and memory_bound(row['overshoot_k'])
                  and row['overshoot_k']['memory'] >= c['reference_overshoot_k']['memory'] + 2)
    small = sum(all(cost(r) < 2 for r in c['classes'].values()) for c in cases)
    return dict(compute_pairs_dominate=a >= 3, memory_limit_binds=b >= 2, stop=small >= 4,
                counts=dict(compute_pairs_dominate=a, memory_limit_binds=b, both_small=small))


def main():
    p = frozen_front.parser(__doc__, CASES)
    p.add_argument('--v3', type=Path, default=Path('docs/evidence/reach-cost-v3.json'))
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    v3 = {c['case']: c for c in json.loads(args.v3.read_text())['cases']}
    cases = [analyse(*frozen_front.paths(args, n), args.workers, v3[f'Case{n}']) for n in args.cases]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/reach-split-plan.md', reach_mm=REACH_MM, seed=SEED,
        verdict=verdict(cases), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
