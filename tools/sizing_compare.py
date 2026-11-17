"""Analysis of run_sizing results (plans: docs/sizing-placement-plan.md section 4, docs/sizing-plan-revisions.md).

Per case and area factor the joint method (shapes merged) and the size-then-place baseline are compared on their
(length, thermal) Pareto fronts with the ATPlace-comparison margin rule; the denominator is the frozen list of
(case, factor) combinations, and a missing or unavailable one makes the overall verdict incomplete. The reticle
decision pairs, under each of 18 cost-parameter sets and on one candidate pool within a common wire budget, the
cheapest finite-cost layout without and with the temperature threshold; only a difference between the two counts
as a thermally driven decision.
"""
import argparse
from dataclasses import replace
import itertools
import json
import math
from pathlib import Path

import numpy as np

from atplace_compare import outcome, pick
from chiplet_floorplanning.placement import pareto_front
from chiplet_floorplanning.placement.cost import CostParams, interposer_cost
from run_sizing import FACTORS

SWEEP = [dict(d0_per_cm2=d0, seam_yield=ys, wafer_usd=w)
         for d0, ys, w in itertools.product((0.06, 0.15, 0.3), (1.0, 0.99, 0.95), (500.0, 1937.0))]
WIRE_SLACK = 1.1


def thermal(row):
    return row['thermal'] if 'thermal' in row else row['peak_c']      # sizing-v1 rows (exploratory) use peak_c


def front_points(rows):
    """(length, thermal) of 16 layouts evenly by length along the rows' Pareto front."""
    if not rows:
        return []
    length = np.array([r['length_m'] for r in rows])
    value = np.array([thermal(r) for r in rows])
    keep = np.asarray(pareto_front(length, value))
    chosen = keep[pick(length[keep])]
    return [(float(length[i]), float(value[i])) for i in chosen]


def compare_budget(record):
    joint = front_points([r for shape in record['joint'] for r in shape['rows']])
    base = front_points(record['baseline']['rows'])
    if not joint or not base:
        return dict(outcome='unavailable', joint_points=len(joint), baseline_points=len(base))
    return outcome(joint, base)


def verdict(outcomes, expected):
    """outcomes: {combination: outcome} for the combinations found; expected: the frozen number of combinations."""
    done = [o for o in outcomes.values() if o in ('ours', 'atplace', 'tie')]
    wins, losses = (sum(o == k for o in done) for k in ('ours', 'atplace'))
    coverage = dict(expected=expected, completed=len(done), unavailable=len(outcomes) - len(done),
                    missing=expected - len(outcomes), wins=wins, losses=losses)
    if len(done) < expected:
        return 'incomplete', coverage
    if wins >= 0.40*expected and losses <= 0.10*expected:
        return 'effective', coverage
    if losses >= 0.25*expected or wins < 0.15*expected:
        return 'ineffective', coverage
    return 'partial', coverage


def candidates(records):
    """Every evaluated layout: (width mm, height mm, thermal, length m, method)."""
    out = []
    for record in records:
        for method, shapes in (('joint', record['joint']), ('baseline', [record['baseline']])):
            out += [(s['width_mm'], s['height_mm'], thermal(r), r['length_m'], method) for s in shapes for r in s['rows']]
    return out


def cheapest(pool, params):
    priced = [(interposer_cost(w, h, params)['total_usd'], w, h) for w, h in set(pool)]
    priced = [p for p in priced if math.isfinite(p[0])]
    if not priced:
        return None
    cost, w, h = min(priced)
    c = interposer_cost(w, h, params)
    return dict(width_mm=w, height_mm=h, option=c['option'], fields=c['fields'], cost_usd=cost)


def reticle_decision(records):
    original = [r for r in records if abs(r['factor'] - 1.0) < 1e-9]
    if not original or not original[0]['baseline']['rows']:
        return dict(status='no original-size baseline')
    base_rows = original[0]['baseline']['rows']
    t_cap = min(thermal(r) for r in base_rows)
    l_cap = WIRE_SLACK*min(r['length_m'] for r in base_rows)
    pool = [c for c in candidates(records) if c[3] <= l_cap + 1e-12]
    pairs, driven = [], 0
    for params in SWEEP:
        p = replace(CostParams(), **params)
        free = cheapest([(w, h) for w, h, _, _, _ in pool], p)
        capped = cheapest([(w, h) for w, h, t, _, _ in pool if t <= t_cap + 1e-9], p)
        thermally = (free is not None and capped is not None
                     and (free['option'], free['fields']) != (capped['option'], capped['fields']))
        driven += thermally
        pairs.append(dict(params=params, without_threshold=free, with_threshold=capped, thermally_driven=thermally))
    status = 'unsupported' if all(x['with_threshold'] is None for x in pairs) else 'ok'
    return dict(status=status, t_cap=t_cap, threshold_kind='baseline coolest at original size (relative)',
                l_cap_m=l_cap, pairs=pairs, thermally_driven_sets=driven)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, required=True, help='directory with caseN/factor*.json')
    p.add_argument('--cases', type=int, nargs='+', default=list(range(1, 11)))
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    cases, outcomes = {}, {}
    for n in args.cases:
        files = sorted((args.runs/f'case{n}').glob('factor*.json'))
        records = [json.loads(f.read_text()) for f in files]
        per = {f"{r['factor']:g}": compare_budget(r) for r in records}
        outcomes.update({(n, k): v['outcome'] for k, v in per.items()})
        cases[f'case{n}'] = dict(budgets=per, reticle=reticle_decision(records) if records else dict(status='no runs'))
        print(f'case{n}', {k: v['outcome'] for k, v in per.items()},
              'thermally driven sets', cases[f'case{n}']['reticle'].get('thermally_driven_sets'), flush=True)
    result, coverage = verdict(outcomes, len(args.cases)*len(FACTORS))
    driven_cases = sum((c['reticle'].get('thermally_driven_sets') or 0) > 0 for c in cases.values())
    args.output.write_text(json.dumps(dict(plan='docs/sizing-plan-revisions.md', verdict=result, coverage=coverage,
                                           reticle_thermally_driven_cases=driven_cases,
                                           reticle_verdict='non_degenerate' if driven_cases >= 3 else 'degenerate',
                                           cases=cases), indent=1, default=float) + '\n')
    print(result, coverage, 'thermally driven reticle decisions in', driven_cases, 'cases')


if __name__ == '__main__':
    main()
