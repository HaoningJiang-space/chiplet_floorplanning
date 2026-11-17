"""Analysis of run_sizing results (plan: docs/sizing-placement-plan.md, sections 4 and 4.1).

Per case and area budget the joint method (shapes merged) and the size-then-place baseline are compared on their
(length, peak) Pareto fronts with the ATPlace-comparison margin rule. The reticle decision takes, per case, the
cheapest layout at or below T_cap (the baseline's coolest peak at the original size) under 18 cost-parameter sets.
"""
import argparse
from dataclasses import replace
import itertools
import json
from pathlib import Path

import numpy as np

from atplace_compare import outcome, pick
from chiplet_floorplanning.placement import pareto_front
from chiplet_floorplanning.placement.cost import CostParams, interposer_cost

SWEEP = [dict(d0_per_cm2=d0, seam_yield=ys, wafer_usd=w)
         for d0, ys, w in itertools.product((0.06, 0.15, 0.3), (1.0, 0.99, 0.95), (500.0, 1937.0))]


def front_points(rows):
    """(length, peak) of 16 layouts evenly by length along the rows' Pareto front."""
    if not rows:
        return []
    length = np.array([r['length_m'] for r in rows])
    peak = np.array([r['peak_c'] for r in rows])
    keep = np.asarray(pareto_front(length, peak))
    chosen = keep[pick(length[keep])]
    return [(float(length[i]), float(peak[i])) for i in chosen]


def compare_budget(record):
    joint = front_points([r for shape in record['joint'] for r in shape['rows']])
    base = front_points(record['baseline']['rows'])
    if not joint or not base:
        return dict(outcome='unavailable', joint_points=len(joint), baseline_points=len(base))
    return outcome(joint, base)


def verdict(outcomes):
    """Section 4: share of (case, budget) combinations won by each side."""
    valid = [o for o in outcomes if o != 'unavailable']
    wins, losses = (sum(o == k for o in valid)/max(len(valid), 1) for k in ('ours', 'atplace'))
    if wins >= 0.40 and losses <= 0.10:
        return 'effective', wins, losses
    if losses >= 0.25 or wins < 0.15:
        return 'ineffective', wins, losses
    return 'partial', wins, losses


def candidates(records):
    """Every evaluated layout as (width mm, height mm, peak degC) over budgets, methods and shapes."""
    out = []
    for record in records:
        for shape in record['joint'] + [record['baseline']]:
            out += [(shape['width_mm'], shape['height_mm'], r['peak_c']) for r in shape['rows']]
    return out


def reticle_decision(records):
    original = [r for r in records if abs(r['factor'] - 1.0) < 1e-9]
    if not original or not original[0]['baseline']['rows']:
        return dict(status='no original-size baseline')
    t_cap = min(r['peak_c'] for r in original[0]['baseline']['rows'])
    feasible = [(w, h) for w, h, t in candidates(records) if t <= t_cap + 1e-9]
    choices = []
    for params in SWEEP:
        p = replace(CostParams(), **params)
        w, h = min(set(feasible), key=lambda s: interposer_cost(*s, p)['total_usd'])
        c = interposer_cost(w, h, p)
        choices.append(dict(params=params, width_mm=w, height_mm=h, option=c['option'], fields=c['fields'],
                            cost_usd=c['total_usd']))
    distinct = {(c['option'], c['fields']) for c in choices}
    return dict(t_cap_c=t_cap, choices=choices, distinct=sorted(map(str, distinct)), changes=len(distinct) > 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, required=True, help='directory with caseN/factor*.json')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    cases, outcomes = {}, []
    for case_dir in sorted(args.runs.glob('case*'), key=lambda d: int(d.name[4:])):
        records = [json.loads(f.read_text()) for f in sorted(case_dir.glob('factor*.json'))]
        if not records:
            continue
        per = {f"{r['factor']:g}": compare_budget(r) for r in records}
        outcomes += [v['outcome'] for v in per.values()]
        cases[case_dir.name] = dict(budgets=per, reticle=reticle_decision(records))
        print(case_dir.name, {k: v['outcome'] for k, v in per.items()},
              'reticle', cases[case_dir.name]['reticle'].get('distinct'), flush=True)
    result, wins, losses = verdict(outcomes)
    changed = sum(c['reticle'].get('changes', False) for c in cases.values())
    args.output.write_text(json.dumps(dict(plan='docs/sizing-placement-plan.md', verdict=result, joint_win_share=wins,
                                           baseline_win_share=losses, reticle_cases_changing=changed,
                                           reticle_verdict='non_degenerate' if changed >= 3 else 'degenerate',
                                           cases=cases), indent=1, default=float) + '\n')
    print(result, round(wins, 2), round(losses, 2), 'reticle changes in', changed, 'cases')


if __name__ == '__main__':
    main()
