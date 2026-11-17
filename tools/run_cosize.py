"""Interposer co-optimisation against a reference quality point (plan: docs/cosize-v3-plan.md, protocol v3.1).

For one case and one reference point (T*, L*) - a layout ATPlace2.5D produced on the original carrier, scored with
our FV and exact pin length - every die gets the absolute limit T* and the exact pin length budget is L*. The
reference layout anchors every method after the shared FV check (cosize.verify_anchor). Methods, each with the same
FV budget, search for the cheapest interposer (cost.interposer_cost, silicon only) carrying a layout that meets both:
- cosize / cosize_axial / cosize_blind / cosize_rs: cosize.anchored with the K-direction proxy MILP, the axial one,
  the min-wire MILP or relation_space (control) as the new-topology step;
- cosize_shrink (v4, docs/cosize-v4-plan.md): continuous carrier-scale SLP with MILP topology moves;
- fixed_aspect: size-then-place - the original aspect ratio, bisection on the area factor, relation_space at each
  size with an equal share of the budget, seeded with the smallest certified layout; the original carrier is
  certified by the checked anchor.
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
from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.cosize import anchored, ceil_grid, fit_into, verify_anchor
from chiplet_floorplanning.placement.methods import NoLegalStart, relation_front
from chiplet_floorplanning.placement.cost import interposer_cost
from atplace_compare import from_atplace

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


def fixed_aspect(problem, gap_um, length_m, fv_budget, seed, milp_s, workers, anchor=None, resolution=64,
                 expected_j_k=0.0):
    """Bisection on the area factor at the original aspect ratio; relation_space per size. With `anchor` (v3.1) the
    reference layout is checked by the shared verify_anchor (1 FV, counted), certifies the original carrier itself
    (step 0, not grid-rounded) with its measured J, and every later size is seeded with the smallest certified
    layout so far mapped into it (fit_into), as cosize.anchored does."""
    w0, h0 = (s/1000 for s in problem.carrier_um)
    die_area = (problem.size_um.prod(axis=1)).sum()/1e6
    low, high = die_area/(w0*h0), ENVELOPE**2          # area factors: certainly infeasible / search ceiling
    best, history, used, check = None, [], 0, None
    base, base_um = anchor, problem.carrier_um
    if anchor is not None:
        if fv_budget < 1:
            return dict(best=None, history=[dict(stop='fv budget before the anchor check')], fv_solves=0, anchor=None)
        check = verify_anchor(problem, anchor, gap_um, length_m, resolution, expected_j_k)
        used = 1
        if not check['ok']:
            return dict(best=None, history=[dict(stop='reproduction_mismatch')], fv_solves=used, anchor=check)
    share = (fv_budget - used)//(BISECTION_STEPS + 1)
    if share < 1:
        best = None
        if anchor is not None and math.isfinite(interposer_cost(w0, h0)['total_usd']):    # the checked anchor stands
            c = interposer_cost(w0, h0)
            best = dict(width_mm=w0, height_mm=h0, cost_usd=c['total_usd'], area_factor=1.0, j_k=check['j_k'],
                        length_m=check['length_m'], centre_um=anchor.centre_um.tolist(),
                        rotation_deg=anchor.rotation_deg.tolist(), die_overshoot_k=check['die_j_k'], step=0,
                        layout_index=0, option=c['option'], fields=c['fields'], anchor=True)
        return dict(best=best, history=[dict(stop='fv budget')], fv_solves=used, anchor=check)
    trial = 1.0
    for step in range(BISECTION_STEPS + 1):
        scale = math.sqrt(trial)
        w, h = (w0, h0) if trial == 1.0 else (ceil_grid(w0*scale), ceil_grid(h0*scale))
        sized = replace(problem, carrier_um=(w*1000, h*1000))
        record = dict(step=step, area_factor=trial, width_mm=w, height_mm=h,
                      cost_usd=interposer_cost(w, h)['total_usd'])
        try:
            if step == 0 and anchor is not None:
                rows = [dict(thermal=check['j_k'], length_m=check['length_m'])]
                archive = dict(solves=0, centre_um=[anchor.centre_um], rotation_deg=[anchor.rotation_deg],
                               die_thermal=[np.array(check['die_j_k'])])
                record['anchor'] = True
            else:
                start = None if base is None else fit_into(sized, base, base_um, gap_um)
                record['started'] = start is not None
                rows, archive = relation_front(sized, gap_um, share, seed, [start] if start is not None else [],
                                          dict(milp_s=milp_s, workers=workers))
            used += int(archive['solves'])
            ok = [i for i, r in enumerate(rows) if r['thermal'] <= 0 and r['length_m'] <= length_m + 1e-9]
            if record.get('anchor'):
                ok = [0]                    # verify_anchor accepted it: |J| <= REPRODUCE_K, length within budget
            record.update(fv_solves=int(archive['solves']), certified=bool(ok),
                          best_j_k=min((r['thermal'] for r in rows if r['length_m'] <= length_m + 1e-9), default=None))
        except NoLegalStart as error:               # no legal start on this size; execution errors propagate
            ok, record['error'], record['certified'] = [], str(error), False
        history.append(record)
        if ok:
            chosen = min(ok, key=lambda i: (rows[i]['thermal'], rows[i]['length_m'], i))
            layout = Layout(np.asarray(archive['centre_um'][chosen]), np.asarray(archive['rotation_deg'][chosen]))
            if anchor is not None and (base is anchor or w*h < base_um[0]*base_um[1]/1e6):
                base, base_um = layout, sized.carrier_um
            if math.isfinite(record['cost_usd']) and (best is None or record['cost_usd'] < best['cost_usd']):
                best = dict(width_mm=w, height_mm=h, cost_usd=record['cost_usd'], area_factor=trial,
                            j_k=rows[chosen]['thermal'], length_m=rows[chosen]['length_m'],
                            centre_um=layout.centre_um.tolist(), rotation_deg=layout.rotation_deg.tolist(),
                            die_overshoot_k=np.asarray(archive['die_thermal'][chosen]).tolist(),
                            step=step, layout_index=chosen, option=interposer_cost(w, h)['option'],
                            fields=interposer_cost(w, h)['fields'])
            high = trial
        else:
            low = trial
        if step == 0 and not ok:
            trial = high                                    # the original size failed: try the ceiling once
            continue
        trial = (low + high)/2
    return dict(best=best, history=history, fv_solves=used, anchor=check)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--evidence', type=Path, default=Path('docs/evidence/atplace-compare-rsg4-v3.json'))
    p.add_argument('--reference', choices=('atp_cool', 'atp_wl'), required=True)
    p.add_argument('--method', choices=('cosize', 'cosize_axial', 'cosize_blind', 'cosize_rs', 'cosize_shrink', 'fixed_aspect'), required=True)
    p.add_argument('--anchor-dir', type=Path, required=True,
                   help='ATPlace layouts CaseN/<label>/layout.json; the reference layout anchors every method')
    p.add_argument('--front-dir', type=Path, default=None,
                   help='reference family B: our exported front CaseN/{manifest.json,kXXX.layout.json}; the anchor is '
                        'the coolest front point within the ATPlace reference length, the limit its FV peak + delta')
    p.add_argument('--delta-k', type=float, default=0.0, help='family B: limit above the front point peak (K)')
    p.add_argument('--fv-solves', type=int, default=1000)
    p.add_argument('--gap-um', type=float, default=0)
    p.add_argument('--milp-s', type=float, default=60)
    p.add_argument('--size-s', type=float, default=120, help='v3.1: MILP seconds per trial carrier, all calls shared')
    p.add_argument('--threads', type=int, default=2, help='v3.1: Gurobi threads per aspect-family process')
    p.add_argument('--directions', type=int, default=8, help='K-direction proxy distance (cosize only)')
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=2)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not (math.isfinite(args.delta_k) and args.delta_k >= 0):
        raise SystemExit('--delta-k must be finite and >= 0 (a limit below the anchor peak would admit an overshooting anchor)')
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    case = json.loads(args.case.read_text())
    problem = Problem.from_imported(case)
    refs = references(args.evidence, problem.name if problem.name.startswith('Case') else args.case.stem)
    if args.reference not in refs:
        raise SystemExit(f'no {args.reference} reference for {args.case.stem}')
    t_ref, l_ref, label = refs[args.reference]
    anchor_file, expected = args.anchor_dir/args.case.stem/label/'layout.json', 0.0
    if args.front_dir is not None:              # family B (docs/cosize-binding-analysis.md section 5)
        front = [r for r in json.loads((args.front_dir/args.case.stem/'manifest.json').read_text())
                 if r['length_m'] <= l_ref + 1e-9]
        if not front:
            raise SystemExit(f'no front point within {l_ref} m for {args.case.stem}')
        point = min(front, key=lambda r: (r['fv_peak_c'], r['length_m']))
        anchor_file, label = args.front_dir/args.case.stem/f"{point['name']}.layout.json", f"front:{point['name']}"
        t_ref, expected = point['fv_peak_c'] + args.delta_k, -args.delta_k
    limited = replace(problem, limit_c=np.full(problem.count, t_ref))
    anchor = from_atplace(problem, json.loads(anchor_file.read_text()))
    started = time.perf_counter()
    if args.method == 'fixed_aspect':
        out = fixed_aspect(limited, args.gap_um, l_ref, args.fv_solves, args.seed, args.milp_s, args.workers, anchor,
                           expected_j_k=expected)
    else:
        inner = dict(cosize='proxy', cosize_axial='axial', cosize_blind='blind', cosize_rs='relation_space',
                     cosize_shrink='shrink')[args.method]
        out = anchored(limited, anchor, args.gap_um, l_ref, args.fv_solves, inner=inner, envelope=ENVELOPE,
                       size_s=args.size_s, threads=args.threads, workers=args.workers, directions=args.directions,
                       seed=args.seed, expected_j_k=expected)
    w0, h0 = (s/1000 for s in problem.carrier_um)
    record = dict(protocol_revision='cosize-v4.1', case=args.case.stem, method=args.method,
                  reference=args.reference, reference_label=label, delta_k=args.delta_k if args.front_dir else None,
                  t_ref_c=t_ref, l_ref_m=l_ref, original=dict(width_mm=w0, height_mm=h0, **{
                      k: v for k, v in interposer_cost(w0, h0).items() if k in ('option', 'fields', 'total_usd')}),
                  seed=args.seed, fv_budget=args.fv_solves, milp_s=args.milp_s, wall_s=time.perf_counter() - started,
                  resources=dict(workers=args.workers, threads=args.threads, size_s=args.size_s),
                  limit_c=limited.limit_c.tolist(), names=list(limited.names), thermal_kind='overshoot_k',
                  case_sha256=hashlib.sha256(args.case.read_bytes()).hexdigest(), code=source_revision(),
                  plan='docs/cosize-v4-plan.md', anchor_file=str(anchor_file),
                  anchor_sha256=hashlib.sha256(anchor_file.read_bytes()).hexdigest(),
                  **out)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=1, default=float) + '\n')
    b = out['best']
    print(args.case.stem, args.reference, args.method, 'best', b and (b['width_mm'], b['height_mm'], round(b['cost_usd'], 2)),
          'original', (w0, h0, round(record['original']['total_usd'], 2)), 'fv', out['fv_solves'],
          round(record['wall_s']), 's', flush=True)


if __name__ == '__main__':
    main()
