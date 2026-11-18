"""cosize v6: successive halving over search mechanisms and shapes within one budget (docs/cosize-v6-plan.md).

Arms, all from the same checked anchor: one free-height joint sizing MILP with the proxy (v1/v2 form, `joint_arm`),
mapping repair plus the min-wire MILP generator (v3.2 blind form, `repair_arm`) and relation_space with resumed
state (`rs_arm`), the last two on the original aspect, 1:3 and 3:1 (shapes within 5% of each other merged). Each arm
is a generator: it keeps its carrier, certified layouts, random stream and position between rounds; the driver
sends a round's FV and time allowance and receives the arm's records. Rounds keep 7 -> 4 -> 2 -> 1 arms with 48, 48,
96 and 192 new FV per surviving arm; round 0 promotes first one progressing arm per mechanism, then by cost. Every
certified layout stays in the global pool; the anchor is the global fallback. Wall time includes everything from the
anchor check on; past the deadline the cheapest certified design so far is returned.
"""
from dataclasses import replace
import math
import time

import numpy as np

from .cosize import (area_ceiling, box, ceil_grid, certify, fit_into, trial_areas, try_carrier, verify_anchor)
from .cost import CostParams, interposer_cost, max_height
from .geometry import is_legal, pin_manhattan_um
from .lp import MILP_STATUS, legalize_relations, milp_relations
from .problem import Layout
from .proxy import R_MM, ThermalProxy

ROUNDS = (48, 48, 96, 192)          # new FV per surviving arm in each round
KEEP = (4, 2, 1)                    # arms kept after rounds 0, 1, 2
ASPECTS = (1/3, 3.0)                # besides the original aspect
CLASSES = ('joint', 'repair', 'rs')


def certified_record(arm, w, h, ok, params, **extra):
    """A certified design of `arm` on a w x h carrier: ok = (layout, J, length)."""
    return dict(arm=arm, width_mm=w, height_mm=h, cost_usd=interposer_cost(w, h, params)['total_usd'], certified=True,
                j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(), rotation_deg=ok[0].rotation_deg.tolist(),
                **extra)


def rs_arm(ctx, aspect, name):
    """relation_space on one aspect. Until something certifies, the targets are the aspect's trial areas from the
    largest down; then each target is halfway between the smallest certified area and the largest failure below it,
    or 10% below the smallest certified area while nothing below has failed. Every step is a real relation_space
    search seeded with the mapped smallest certified layout (the anchor first), on the arm's own continuing random
    stream, so a later round resumes rather than restarts."""
    from .methods import NoLegalStart, relation_front
    rng = np.random.default_rng([ctx['seed'], sum(map(ord, name))])
    low = ctx['die_area']
    high = area_ceiling(aspect, low, ctx['a_max'], ctx['cap'], ctx['params'])
    areas = [] if high is None else trial_areas(aspect, low, high, ctx['params'])
    base, base_um, good, bad = ctx['anchor'], ctx['problem'].carrier_um, None, None
    allowance = yield []
    while True:
        if good is None and not areas:
            allowance = yield [dict(arm=name, stop='no trial carrier left')]
            continue
        area = areas.pop(0) if good is None else (good + bad)/2 if bad is not None else max(low, 0.9*good)
        w, h = box(area, aspect)
        sized = replace(ctx['problem'], carrier_um=(w*1000, h*1000))
        start = fit_into(sized, base, base_um, ctx['gap_um'])
        budget, time_s = allowance
        began = time.perf_counter()
        try:
            rows, archive = relation_front(sized, ctx['gap_um'], budget, rng, [start],
                                           dict(milp_s=max(1.0, min(60.0, time_s/2)), workers=ctx['workers'],
                                                resolution=ctx['resolution']))
        except NoLegalStart:
            rows, archive = [], dict(solves=0)
        within = [i for i, r in enumerate(rows) if r['length_m'] <= ctx['length_m'] + 1e-9]
        good_rows = [i for i in within if rows[i]['thermal'] <= 0]
        rec = dict(arm=name, area_mm2=area, width_mm=w, height_mm=h, fv_solves=int(archive['solves']),
                   seconds=time.perf_counter() - began, cost_usd=interposer_cost(w, h, ctx['params'])['total_usd'],
                   certified=bool(good_rows), wire_ok_j_k=min((rows[i]['thermal'] for i in within), default=None))
        out = [rec]
        if good_rows:
            i = min(good_rows, key=lambda i: (rows[i]['thermal'], rows[i]['length_m'], i))
            layout = Layout(np.asarray(archive['centre_um'][i]), np.asarray(archive['rotation_deg'][i]))
            out.append(certified_record(name, w, h, (layout, rows[i]['thermal'], rows[i]['length_m']), ctx['params']))
            base, base_um, good = layout, sized.carrier_um, area
            if bad is not None and bad >= good:
                bad = None
        elif good is not None:
            bad = area if bad is None else max(bad, area)
        allowance = yield out


def repair_arm(ctx, aspect, name):
    """v3.2 blind on one aspect: the trial areas from the largest down, each the mapped smallest certified layout
    repaired by the SLP chain, then the min-wire MILP; a failure goes on, only a proof ends the arm; then up to two
    bisections below the smallest certified area. Trials proceed while the round's allowance lasts."""
    low = ctx['die_area']
    high = area_ceiling(aspect, low, ctx['a_max'], ctx['cap'], ctx['params'])
    areas = [] if high is None else trial_areas(aspect, low, high, ctx['params'])
    base, base_um, good, failed, refine = ctx['anchor'], ctx['problem'].carrier_um, None, [], 2
    allowance = yield []
    while True:
        budget, time_s = allowance
        out, used, began = [], 0, time.perf_counter()
        while budget - used > 1 and time.perf_counter() - began < time_s:
            if areas:
                area = areas.pop(0)
            elif good is not None and refine and failed:
                lower = max((a for a in failed if a < good), default=low)   # nothing failed below: the die area
                area, refine = (good + lower)/2, refine - 1
            else:
                out.append(dict(arm=name, stop='trials exhausted'))
                break
            w, h = box(area, aspect)
            sized = replace(ctx['problem'], carrier_um=(w*1000, h*1000))
            rec, ok, n = try_carrier(sized, base, base_um, ctx['gap_um'], ctx['length_m'], ['blind'], budget - used,
                                     max(1.0, min(120.0, time_s - (time.perf_counter() - began))), ctx['threads'],
                                     None, ctx['resolution'], ctx['chain_steps'], ctx['seed'], ctx['workers'])
            used += n
            rec.update(arm=name, area_mm2=area, width_mm=w, height_mm=h, fv_solves=n, certified=ok is not None,
                       cost_usd=interposer_cost(w, h, ctx['params'])['total_usd'],
                       wire_ok_j_k=min((st['best_j_k'] for st in rec['stages'] if st.get('best_j_k') is not None
                                        and st.get('best_length_m', math.inf) <= ctx['length_m'] + 1e-9), default=None))
            out.append(rec)
            if ok is not None:
                out.append(certified_record(name, w, h, ok, ctx['params']))
                base, base_um = ok[0], sized.carrier_um
                good = area if good is None else min(good, area)
            else:
                failed.append(area)
                if rec.get('status') == 'proven_infeasible':
                    areas = [a for a in areas if a > area]
        allowance = yield out


def joint_arm(ctx, name, levels_step=0.5, aspect_limit=3.0):
    """v1/v2 joint sizing: per exposure-field option, the min-area MILP over width levels with a free height, the
    proxy envelope capped at -margin and the clustered wire within budget; candidates certified in cost order by the
    SLP chain; the margin follows the FV (success: += J; failure: += max(J, 0.25)); a certified design caps the next
    area at 98% of it."""
    p, gap = ctx['problem'], ctx['gap_um']
    w_max, h_max = (s/1000*1.25 for s in p.carrier_um)
    envelope = replace(p, carrier_um=(w_max*1000, h_max*1000))
    narrow = p.size_um.min(axis=1).max()/1000
    levels = np.arange(math.ceil(narrow/levels_step)*levels_step, w_max + 1e-9, levels_step)
    model, margin, area_cap = ctx['model'], ctx['joint_margin'], None
    allowance = yield []
    while True:
        budget, time_s = allowance
        out, used, began = [], 0, time.perf_counter()
        found = []
        for k in (1, 2, 3, 4):
            left = time_s - (time.perf_counter() - began)
            if left < 2:
                break
            caps = np.array([min(max_height(w, k, h_max, ctx['params']), aspect_limit*w) for w in levels])
            excluded = [l for l, w in enumerate(levels) if caps[l] < w/aspect_limit]
            if len(excluded) == len(levels):
                continue
            sizing = (levels, area_cap, excluded, caps, True, levels/aspect_limit)
            res = milp_relations(envelope, gap, left/2, sizing=sizing, proxy=(model, -margin, ctx['length_m']*1000),
                                 threads=ctx['threads'], focus=1)
            out.append(dict(arm=name, fields=k, solver=MILP_STATUS['status'], margin_k=margin))
            if res is None:
                continue
            layout, extent, _ = res
            w, h = (ceil_grid(v) for v in extent)
            w, h = max(w, ceil_grid(h/aspect_limit)), max(h, ceil_grid(w/aspect_limit))
            cost = interposer_cost(w, h, ctx['params'])['total_usd']
            if math.isfinite(cost):
                found.append((cost, w, h, layout))
        js = []
        for cost, w, h, layout in sorted(found, key=lambda f: f[0]):
            if budget - used <= 1:
                break
            sized = replace(p, carrier_um=(w*1000, h*1000))
            legal = legalize_relations(sized, layout, gap)
            if legal is None or not is_legal(sized, legal, gap):
                continue
            ok, (j, l), n = certify(sized, legal, gap, ctx['length_m'], min(ctx['chain_steps'], budget - used - 1),
                                    ctx['resolution'])
            used += n
            out.append(dict(arm=name, width_mm=w, height_mm=h, cost_usd=cost, fv_solves=n, certified=ok is not None,
                            best_j_k=j, wire_ok_j_k=j if l <= ctx['length_m'] + 1e-9 else None))
            js.append(j)
            if ok is not None:
                out.append(certified_record(name, w, h, ok, ctx['params']))
                area_cap, margin = 0.98*w*h, margin + ok[1]
                break
        else:
            margin += max(max(js, default=0.0), 0.25)
        allowance = yield out


def best_cost(records):
    return min((r['cost_usd'] for r in records if r.get('certified') and 'centre_um' in r), default=math.inf)


def closest_overshoot(records):
    """The smallest measured overshoot among the arm's layouts that met the exact pin budget (same layout)."""
    return min((r['wire_ok_j_k'] for r in records if r.get('wire_ok_j_k') is not None), default=math.inf)


def promote(arms, keep, first_round):
    """The arms to keep: round 0 first takes the cheapest progressing arm of every mechanism class, then fills by
    (own best certified cost, closest measured overshoot, fixed order)."""
    key = lambda a: (best_cost(a['records']), closest_overshoot(a['records']), a['order'])   # noqa: E731
    ranked = sorted(arms, key=key)
    chosen = []
    if first_round:
        for kind in CLASSES:
            progress = [a for a in ranked if a['kind'] == kind and math.isfinite(best_cost(a['records']))]
            if progress and len(chosen) < keep:
                chosen.append(progress[0])
    for a in ranked:
        if len(chosen) >= keep:
            break
        if a not in chosen:
            chosen.append(a)
    return chosen


def successive_halving(problem, anchor, gap_um, length_m, fv_budget=1000, wall_s=2400.0, envelope=1.25,
                       resolution=64, chain_steps=12, threads=16, workers=16, seed=2, params=CostParams(),
                       expected_j_k=0.0):
    """cosize v6 (module docstring). Returns the cheapest certified design, every arm's records, rounds, FV and
    seconds; all FV solves (anchor check, calibration, every arm) count against fv_budget."""
    started = time.perf_counter()
    out = dict(best=None, history=[], rounds=[], fv_solves=0, calibration_solves=0, anchor=None, inner='sh')
    if fv_budget < 1:
        out['history'].append(dict(stop='fv budget before the anchor check'))
        return out
    check = verify_anchor(problem, anchor, gap_um, length_m, resolution, expected_j_k)
    out.update(anchor=check, fv_solves=1)
    if not check['ok']:
        out['history'].append(dict(stop='reproduction_mismatch'))
        return out
    w0, h0 = (s/1000 for s in problem.carrier_um)
    c0 = interposer_cost(w0, h0, params)
    pool = []
    if math.isfinite(c0['total_usd']):
        pool.append(certified_record('anchor', w0, h0, (anchor, check['j_k'], check['length_m']), params))
    calibration = len(R_MM) + len({tuple(s) for s in problem.size_um})
    model = ThermalProxy.calibrate(problem, gap_um, resolution) if fv_budget - 1 >= calibration else None
    if model is not None:
        out['fv_solves'] += model.solves
        out['calibration_solves'] = model.solves
    ctx = dict(problem=problem, anchor=anchor, gap_um=gap_um, length_m=length_m, params=params, seed=seed,
               workers=workers, threads=threads, resolution=resolution, chain_steps=chain_steps, model=model,
               die_area=float(problem.size_um.prod(axis=1).sum())/1e6, a_max=w0*h0*envelope**2,
               cap=c0['total_usd'], joint_margin=0.0)
    if model is not None:                               # the joint arm's proxy offset, from the anchor (no FV)
        ctx['joint_margin'] = -(model.envelope_value(problem, anchor, gap_um) - check['j_k'])
    shapes = [w0/h0] + [a for a in ASPECTS if all(abs(math.log(a/b)) > math.log(1.05) for b in [w0/h0])]
    arms = []
    if model is not None:
        arms.append(dict(name='joint', kind='joint', gen=joint_arm(ctx, 'joint')))
    for kind, make in (('repair', repair_arm), ('rs', rs_arm)):
        for a in shapes:
            name = f'{kind}:{a:.3f}'
            arms.append(dict(name=name, kind=kind, gen=make(ctx, a, name)))
    for k, a in enumerate(arms):
        a.update(order=k, records=[], fv=0)
        next(a['gen'])
    alive = arms
    for r, per_arm in enumerate(ROUNDS):
        deadline_left = wall_s - (time.perf_counter() - started)
        fv_left = fv_budget - out['fv_solves']
        if deadline_left <= 0 or fv_left <= 1:
            out['rounds'].append(dict(round=r, stop='deadline' if deadline_left <= 0 else 'fv budget'))
            break
        round_fv = min(per_arm, fv_left//len(alive))
        for a in alive:
            left = wall_s - (time.perf_counter() - started)
            if left <= 0:
                break                                    # nothing is started after the deadline
            time_s = max(1.0, left*round_fv/max(1, fv_budget - out['fv_solves']))
            budget = min(round_fv, fv_budget - out['fv_solves'])
            if budget <= 1:
                break
            recs = a['gen'].send((budget, time_s))
            if time.perf_counter() - started > wall_s:   # returned after the deadline: its designs do not count
                for x in recs:
                    if x.get('certified'):
                        x['certified'], x['after_deadline'] = False, True
            used = sum(x.get('fv_solves', 0) for x in recs if 'centre_um' not in x)
            a['records'] += recs
            a['fv'] += used
            out['fv_solves'] += used
            pool += [x for x in recs if x.get('certified') and 'centre_um' in x]
        summary = [dict(arm=a['name'], best_usd=best_cost(a['records']), fv=a['fv']) for a in alive]
        if r < len(KEEP):
            alive = promote(alive, KEEP[r], r == 0)
        out['rounds'].append(dict(round=r, arms=summary, kept=[a['name'] for a in alive],
                                  seconds=time.perf_counter() - started, fv_solves=out['fv_solves']))
    for a in arms:
        out['history'] += a['records']
    if pool:
        best = min(pool, key=lambda x: x['cost_usd'])
        c = interposer_cost(best['width_mm'], best['height_mm'], params)
        out['best'] = dict(best, option=c['option'], fields=c['fields'], anchor=best['arm'] == 'anchor')
    out['search_wall_s'] = time.perf_counter() - started    # the runner records its own wall_s
    return out
