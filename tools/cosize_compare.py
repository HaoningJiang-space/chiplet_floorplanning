"""Frozen comparison of cosize runs (plans: docs/cosize-plan.md "判定", docs/cosize-v3-plan.md; protocol v3.1).

Per (case, reference) combination and pair of methods: the cheapest FV-certified interposer each found; a win is a
cost <= 0.95x the opponent's, a loss >= 1.05x, only one side certified -> that side wins, neither -> unavailable.
The denominator is the frozen combination list; a missing run or an unavailable combination counts in it.
Also reported: savings against ATPlace's original interposer (finite costs only), whether each win/loss holds under
the 18 cost-parameter sets (each side re-priced over every design it certified), FV solves, wall time and
reticle option changes.
"""
import argparse
import itertools
from dataclasses import replace
import json
import math
from pathlib import Path

from chiplet_floorplanning.placement.cost import CostParams, interposer_cost

# 18 cost-parameter sets: defect density, stitch-seam yield, wafer price (docs/sizing-placement-plan.md).
SWEEP = [dict(d0_per_cm2=d0, seam_yield=ys, wafer_usd=w)
         for d0, ys, w in itertools.product((0.06, 0.15, 0.3), (1.0, 0.99, 0.95), (500.0, 1937.0))]

COMPARISONS = (('cosize', 'fixed_aspect'), ('cosize', 'cosize_blind'), ('cosize', 'cosize_axial'),
               ('cosize_shrink', 'fixed_aspect'))   # v4 (docs/cosize-v4-plan.md); missing runs make it incomplete


def combos(with_case8_cool=False):
    out = [(n, 'atp_wl') for n in range(1, 11)] + [(n, 'atp_cool') for n in range(1, 8)]
    return out + ([(8, 'atp_cool')] if with_case8_cool else [])


def certified(record):
    """(width, height) of every design the run certified (history records), plus the reported best and, when the
    shared anchor check passed, the original carrier itself: under re-priced costs it may be the cheapest."""
    sizes = {(h['width_mm'], h['height_mm']) for h in record.get('history', []) if h.get('certified')}
    if (record.get('anchor') or {}).get('ok'):
        sizes.add(tuple(record['anchor']['carrier_mm']))
    if record.get('best'):
        sizes.add((record['best']['width_mm'], record['best']['height_mm']))
    return sizes


def cheapest(sizes, params=CostParams()):
    costs = [interposer_cost(w, h, params)['total_usd'] for w, h in sizes]
    costs = [c for c in costs if math.isfinite(c)]
    return min(costs) if costs else None


def outcome(ours, theirs):
    if ours is None and theirs is None:
        return 'unavailable'
    if theirs is None:
        return 'win'
    if ours is None:
        return 'loss'
    return 'win' if ours <= 0.95*theirs else 'loss' if ours >= 1.05*theirs else 'tie'


def verdict(outcomes, expected):
    wins, losses = (sum(o == k for o in outcomes.values()) for k in ('win', 'loss'))
    coverage = dict(expected=expected, found=len(outcomes), wins=wins, losses=losses,
                    ties=sum(o == 'tie' for o in outcomes.values()),
                    unavailable=sum(o == 'unavailable' for o in outcomes.values()), missing=expected - len(outcomes))
    if coverage['missing']:
        return 'incomplete', coverage                   # no verdict while runs are missing or unpaired
    if wins >= 0.40*expected and losses <= 0.10*expected:
        return 'effective', coverage
    if losses >= 0.25*expected or wins < 0.15*expected:
        return 'ineffective', coverage
    return 'partial', coverage


IDENTITY = ('protocol_revision', 'case_sha256', 'anchor_sha256', 't_ref_c', 'l_ref_m', 'seed', 'fv_budget')
# delta_k (family B) is covered by t_ref_c, which includes it.


def mismatch(a, b):
    """Identity fields missing from either run or differing between them (such runs must not be paired)."""
    return [k for k in IDENTITY if a.get(k) is None or b.get(k) is None or a[k] != b[k]]


def compare(runs, combos_list):
    def load(n, ref, label):
        f = runs/f'case{n}-{ref}-{label}.json'
        return json.loads(f.read_text()) if f.exists() else None
    report = {}
    for ours, theirs in COMPARISONS:
        outcomes, rows = {}, {}
        for n, ref in combos_list:
            a, b = load(n, ref, ours), load(n, ref, theirs)
            if a is None or b is None:
                continue
            if mismatch(a, b):
                rows[f'case{n}-{ref}'] = dict(outcome='unpaired', mismatch=mismatch(a, b))
                continue
            sa, sb = certified(a), certified(b)
            ca, cb = cheapest(sa), cheapest(sb)
            o = outcome(ca, cb)
            sweep = [outcome(cheapest(sa, replace(CostParams(), **p)), cheapest(sb, replace(CostParams(), **p))) for p in SWEEP]
            outcomes[f'case{n}-{ref}'] = o
            rows[f'case{n}-{ref}'] = dict(outcome=o, ours_usd=ca, theirs_usd=cb, sweep_same=sum(s == o for s in sweep),
                                          ours_fv=a.get('fv_solves'), theirs_fv=b.get('fv_solves'),
                                          ours_wall_s=a.get('wall_s'), theirs_wall_s=b.get('wall_s'),
                                          ours_best=a.get('best') and {k: a['best'][k] for k in ('width_mm', 'height_mm', 'option', 'fields') if k in a['best']},
                                          theirs_best=b.get('best') and {k: b['best'][k] for k in ('width_mm', 'height_mm', 'option', 'fields') if k in b['best']},
                                          original=a.get('original'))
        result, coverage = verdict(outcomes, len(combos_list))
        report[f'{ours}_vs_{theirs}'] = dict(verdict=result, coverage=coverage, rows=rows)
        print(f'{ours} vs {theirs}:', result, coverage, flush=True)
    savings = {}
    for n, ref in combos_list:
        a = load(n, ref, 'cosize')
        if a and a.get('best') and math.isfinite(a['original']['total_usd']):
            savings[f'case{n}-{ref}'] = 1 - a['best']['cost_usd']/a['original']['total_usd']
    report['cosize_savings_vs_original'] = savings
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, required=True)
    p.add_argument('--with-case8-cool', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = compare(args.runs, combos(args.with_case8_cool))
    args.output.write_text(json.dumps(dict(plan='docs/cosize-v3-plan.md', **report), indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
