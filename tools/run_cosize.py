"""Interposer co-optimisation against a reference quality point (plan: docs/cosize-plan.md).

For one case and one reference point (T*, L*) - by default a layout ATPlace2.5D produced on the original carrier,
scored with our FV and exact pin length - every die gets the absolute limit T* and the exact pin length budget is
L*. Three methods search for the cheapest interposer (cost.interposer_cost, silicon only) carrying a layout that
meets both, each with the same FV budget:
- cosize:       joint size/reticle/placement MILP with the proxy, FV-certified (placement/cosize.py);
- cosize_blind: the same without the proxy (min-wire MILP under a bisected area cap), FV-certified;
- fixed_aspect: size-then-place - the original aspect ratio, bisection on the area factor, relation_space at each
                size with an equal share of the budget; a size passes if any evaluated layout meets both.
v3 (--anchor-dir, docs/cosize-v3-plan.md): the reference layout itself anchors every method (it meets both limits
on the original carrier); cosize / cosize_axial / cosize_blind are cosize.anchored with the K-direction proxy, the
axial proxy or no proxy, and fixed_aspect certifies its original-size step with the anchor.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.placement import Problem
from chiplet_floorplanning.placement.cosize import anchored, ceil_grid, cosize
from chiplet_floorplanning.placement.cost import interposer_cost
from atplace_compare import from_atplace
from run_sizing import run_front

ENVELOPE = 1.25
BISECTION_STEPS = 5


def references(evidence, case):
    """{'atp_cool': (T*, L*), 'atp_wl': (T, L)} from an atplace_compare JSON (legal ATPlace points with FV)."""
    entry = next(c for c in json.loads(Path(evidence).read_text())['cases'] if c['case'] == case)
    points = [p for p in entry['atplace'] if p.get('legal') and p.get('fv_peak_c') is not None]
    out = {}
    thermal = [p for p in points if p['label'] != 'wl']
    if thermal:
        best = min(thermal, key=lambda p: (p['fv_peak_c'], p['length_m']))
        out['atp_cool'] = (best['fv_peak_c'], best['length_m'], best['label'])
    wl = [p for p in points if p['label'] == 'wl']
    if wl:
        out['atp_wl'] = (wl[0]['fv_peak_c'], wl[0]['length_m'], 'wl')
    return out


def fixed_aspect(problem, gap_um, length_m, fv_budget, seed, milp_s, workers, anchor=None):
    """Bisection on the area factor at the original aspect ratio; relation_space per size. With `anchor` (v3: the
    reference layout, known to meet both limits on the original carrier) step 0 is certified by it, without FV."""
    w0, h0 = (s/1000 for s in problem.carrier_um)
    die_area = (problem.size_um.prod(axis=1)).sum()/1e6
    low, high = die_area/(w0*h0), ENVELOPE**2          # area factors: certainly infeasible / search ceiling
    share, best, history, used = fv_budget//(BISECTION_STEPS + 1), None, [], 0
    if share < 1:
        return dict(best=None, history=[dict(stop='fv budget')], fv_solves=0)
    trial = 1.0
    for step in range(BISECTION_STEPS + 1):
        scale = math.sqrt(trial)
        w, h = ceil_grid(w0*scale), ceil_grid(h0*scale)
        sized = replace(problem, carrier_um=(w*1000, h*1000))
        record = dict(step=step, area_factor=trial, width_mm=w, height_mm=h,
                      cost_usd=interposer_cost(w, h)['total_usd'])
        try:
            if step == 0 and anchor is not None:
                rows = [dict(thermal=0.0, length_m=length_m)]
                archive = dict(solves=0, centre_um=[anchor.centre_um], rotation_deg=[anchor.rotation_deg],
                               die_thermal=[np.zeros(problem.count)])
                record['anchor'] = True
            else:
                rows, archive = run_front(sized, gap_um, share, seed, [], dict(milp_s=milp_s, workers=workers))
            used += int(archive['solves'])
            ok = [i for i, r in enumerate(rows) if r['thermal'] <= 0 and r['length_m'] <= length_m + 1e-9]
            record.update(fv_solves=int(archive['solves']), certified=bool(ok),
                          best_j_k=min((r['thermal'] for r in rows if r['length_m'] <= length_m + 1e-9), default=None))
        except RuntimeError as error:
            ok, record['error'], record['certified'] = [], str(error), False
        history.append(record)
        if ok:
            if math.isfinite(record['cost_usd']) and (best is None or record['cost_usd'] < best['cost_usd']):
                chosen = min(ok, key=lambda i: (rows[i]['thermal'], rows[i]['length_m'], i))
                best = dict(width_mm=w, height_mm=h, cost_usd=record['cost_usd'], area_factor=trial,
                            j_k=rows[chosen]['thermal'], length_m=rows[chosen]['length_m'],
                            centre_um=archive['centre_um'][chosen].tolist(),
                            rotation_deg=archive['rotation_deg'][chosen].tolist(),
                            die_overshoot_k=archive['die_thermal'][chosen].tolist(),
                            step=step, layout_index=chosen, option=interposer_cost(w, h)['option'],
                            fields=interposer_cost(w, h)['fields'])
            high = trial
        else:
            low = trial
        if step == 0 and not ok:
            trial = high                                    # the original size failed: try the ceiling once
            continue
        trial = (low + high)/2
    return dict(best=best, history=history, fv_solves=used)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--evidence', type=Path, default=Path('docs/evidence/atplace-compare-rsg4-v2.json'))
    p.add_argument('--reference', choices=('atp_cool', 'atp_wl'), required=True)
    p.add_argument('--method', choices=('cosize', 'cosize_axial', 'cosize_blind', 'fixed_aspect'), required=True)
    p.add_argument('--anchor-dir', type=Path, default=None,
                   help='v3: ATPlace layouts CaseN/<label>/layout.json; the reference layout anchors every method')
    p.add_argument('--fv-solves', type=int, default=1000)
    p.add_argument('--gap-um', type=float, default=0)
    p.add_argument('--milp-s', type=float, default=60)
    p.add_argument('--rounds', type=int, default=12)
    p.add_argument('--directions', type=int, default=None, help='K-direction proxy distance (cosize only; v2: 8)')
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=2)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    case = json.loads(args.case.read_text())
    problem = Problem.from_imported(case)
    refs = references(args.evidence, problem.name if problem.name.startswith('Case') else args.case.stem)
    if args.reference not in refs:
        raise SystemExit(f'no {args.reference} reference for {args.case.stem}')
    t_ref, l_ref, label = refs[args.reference]
    limited = replace(problem, limit_c=np.full(problem.count, t_ref))
    anchor, anchor_file = None, None
    if args.anchor_dir is not None:
        anchor_file = args.anchor_dir/args.case.stem/label/'layout.json'
        anchor = from_atplace(problem, json.loads(anchor_file.read_text()))
    started = time.perf_counter()
    if args.method == 'fixed_aspect':
        out = fixed_aspect(limited, args.gap_um, l_ref, args.fv_solves, args.seed, args.milp_s, args.workers, anchor)
    elif anchor is not None:
        inner = dict(cosize='proxy', cosize_axial='axial', cosize_blind='blind')[args.method]
        out = anchored(limited, anchor, args.gap_um, l_ref, args.fv_solves, inner=inner, envelope=ENVELOPE,
                       milp_s=args.milp_s, directions=args.directions or 8)
    elif args.method == 'cosize_axial':
        raise SystemExit('cosize_axial before v3: run cosize without --directions')
    else:
        out = cosize(limited, args.gap_um, l_ref, args.fv_solves, thermal=args.method == 'cosize', envelope=ENVELOPE,
                     rounds=args.rounds, milp_s=args.milp_s, directions=args.directions)
    w0, h0 = (s/1000 for s in problem.carrier_um)
    v3 = anchor is not None
    record = dict(protocol_revision='cosize-v3' if v3 else 'cosize-v2', case=args.case.stem, method=args.method,
                  reference=args.reference, reference_label=label,
                  t_ref_c=t_ref, l_ref_m=l_ref, original=dict(width_mm=w0, height_mm=h0, **{
                      k: v for k, v in interposer_cost(w0, h0).items() if k in ('option', 'fields', 'total_usd')}),
                  seed=args.seed, fv_budget=args.fv_solves, milp_s=args.milp_s, wall_s=time.perf_counter() - started,
                  limit_c=limited.limit_c.tolist(), names=list(limited.names), thermal_kind='overshoot_k',
                  case_sha256=hashlib.sha256(args.case.read_bytes()).hexdigest(), code=source_revision(),
                  plan='docs/cosize-v3-plan.md' if v3 else 'docs/cosize-plan.md',
                  anchor_file=None if anchor_file is None else str(anchor_file),
                  anchor_sha256=None if anchor_file is None else hashlib.sha256(anchor_file.read_bytes()).hexdigest(),
                  **out)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=1, default=float) + '\n')
    b = out['best']
    print(args.case.stem, args.reference, args.method, 'best', b and (b['width_mm'], b['height_mm'], round(b['cost_usd'], 2)),
          'original', (w0, h0, round(record['original']['total_usd'], 2)), 'fv', out['fv_solves'],
          round(record['wall_s']), 's', flush=True)


if __name__ == '__main__':
    main()
