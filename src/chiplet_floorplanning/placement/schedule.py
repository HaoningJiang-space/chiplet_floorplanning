"""cosize v7 / v8: one size schedule shared by the mechanisms, a fixed cost-ordered cascade per target carrier
(docs/cosize-v7-plan.md, docs/cosize-v8-plan.md). v8 adds two cascade stages between the repair and relation_space:
the parent's binding chain flipped (`chain_flip`: the longest path of the separation graph is the smallest carrier
that keeps the parent's relations; links of that chain are moved to the other axis, LP only, then the SLP repair)
and the min-wire MILP generator (v6 / v3.2 blind's), whose infeasibility proves the box and smaller ones out.

Per shape (the original aspect, 1:3, 3:1; merged within 5%) a queue of target areas is kept between the smallest
certified area `hi` (at first the largest carrier cheaper than the anchor's) and the proven lower bound `lo` (at
first the dies' total area); the first target is the interval's midpoint. A target is tried by, in this fixed order, (1) the shape's smallest certified layout
moved without scaling (centred, when the target holds it; one FV) or else mapped proportionally and repaired by the
SLP chain (at most REPAIR_FV), then (2) relation_space on the target (at most RS_FV), seeded with those layouts, on the
shape's own continuing random stream. A success sets hi and puts the lower half's midpoint at the head of the queue.
An ordinary failure is not a proof: the midpoints towards hi and towards lo both join the end of the queue, so the
lower half is still visited. Only a
MILP infeasibility of the geometry and wire relaxation (none is run here) or a shared proof would raise lo. Each shape
has at most TARGETS distinct grid sizes; the shapes take turns. The free-shape joint MILP then uses what is left
(at most JOINT_S of wall time over the 1-4 field options), its certified designs going to the global pool only.
Every count starts at one absolute deadline set before the anchor check; nothing starts after it and nothing
returned after it counts.
"""
from dataclasses import replace
import math
import time

import numpy as np

from .cosize import area_ceiling, box, certify, fit_into, verify_anchor
from .cost import CostParams, interposer_cost
from .geometry import is_legal, pin_manhattan_um
from .lp import legalize_relations
from .problem import Layout
from .proxy import R_MM, ThermalProxy

REPAIR_FV, RS_FV, TARGETS, JOINT_S, MILP_S = 13, 36, 6, 60.0, 60.0
SHAPES = (1/3, 3.0)


def centred(layout, source_um, target_um):
    """The layout moved, unscaled, so that its carrier's centre lands on the target carrier's centre."""
    shift = (np.asarray(target_um) - np.asarray(source_um))/2
    return replace(layout, centre_um=layout.centre_um + shift)


def min_extent(problem, layout, relations, gap_um):
    """Smallest carrier width and height that keep `relations` ((i, j, axis, sign), as centre_relations gives them):
    per axis the longest path of the separation graph, half sizes at both ends. Returns ((w_mm, h_mm), chains) with
    each axis's critical chain as a list of dies."""
    n = problem.count
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
    gap = gap_um/1000
    extent, chains = [], []
    for axis in (0, 1):
        succ = [[] for _ in range(n)]
        indeg = np.zeros(n, int)
        for i, j, a, sign in relations:
            if a == axis:
                first, second = (i, j) if sign > 0 else (j, i)
                succ[first].append(second)
                indeg[second] += 1
        dist, prev = size[:, axis]/2, [-1]*n
        dist = dist.copy()
        order = [k for k in range(n) if indeg[k] == 0]
        for k in order:                                  # Kahn's order; the relations from centres are acyclic
            for m in succ[k]:
                d = dist[k] + (size[k, axis] + size[m, axis])/2 + gap
                if d > dist[m]:
                    dist[m], prev[m] = d, k
                indeg[m] -= 1
                if indeg[m] == 0:
                    order.append(m)
        end = int(np.argmax(dist + size[:, axis]/2))
        chain = [end]
        while prev[chain[-1]] >= 0:
            chain.append(prev[chain[-1]])
        extent.append(float(dist[end] + size[end, axis]/2))
        chains.append(chain[::-1])
    return tuple(extent), chains


def chain_flip(sized, layout, gap_um, max_flips=3):
    """Relations that fit `sized`: starting from the layout's centre relations, while an axis's longest chain is
    longer than the carrier, flip the chain link whose move to the other axis lowers the worse overflow most (the
    side taken from the centres). Then the exact length LP inside the carrier gives the layout. LP only, no FV.
    Returns (layout or None, flips)."""
    from .lp import TopologyLP, centre_relations
    w, h = (v/1000 for v in sized.carrier_um)
    rel = {(i, j): (axis, sign) for i, j, axis, sign in centre_relations(sized, layout, gap_um)}
    c = layout.centre_um
    as_list = lambda r: [(i, j, a, s) for (i, j), (a, s) in r.items()]    # noqa: E731
    over = lambda e: max(e[0] - w, e[1] - h)                              # noqa: E731
    flips = 0
    extent, chains = min_extent(sized, layout, as_list(rel), gap_um)
    while over(extent) > 1e-9 and flips < max_flips:
        axis = 0 if extent[0] - w >= extent[1] - h else 1
        chain, best = chains[axis], None
        for a, b in zip(chain, chain[1:]):
            i, j = min(a, b), max(a, b)
            trial = dict(rel)
            trial[(i, j)] = (1 - axis, 1 if c[j, 1 - axis] >= c[i, 1 - axis] else -1)
            e, ch = min_extent(sized, layout, as_list(trial), gap_um)
            if best is None or over(e) < best[0]:
                best = (over(e), trial, e, ch)
        if best is None or best[0] >= over(extent) - 1e-9:
            return None, flips                           # no single flip shortens the binding chain
        _, rel, extent, chains = best
        flips += 1
    if over(extent) > 1e-9:
        return None, flips
    lp = TopologyLP(sized, layout, gap_um, pairs=0, relations=as_list(rel))
    x = lp._solve(lp.length)
    return (None if x is None else lp._layout(x)), flips


def cascade(ctx, shape, area, deadline):
    """Try one target carrier of `shape`: unscaled move, else mapping + SLP repair; with v8 then the chain flip and
    the min-wire MILP generator; then relation_space (skipped once the MILP proves the box infeasible). Returns the
    target record (each stage: executed, FV, seconds, certified, wire-feasible overshoot) and the certified
    (layout, J, length) or None."""
    from .methods import NoLegalStart, relation_front
    w, h = box(area, shape['aspect'])
    sized = replace(ctx['problem'], carrier_um=(w*1000, h*1000))
    rec = dict(aspect=shape['aspect'], area_mm2=area, width_mm=w, height_mm=h, stages=[],
               cost_usd=interposer_cost(w, h, ctx['params'])['total_usd'], fv_solves=0)
    base, base_um, L = shape['base'], shape['base_um'], ctx['length_m']
    ok, starts = None, []

    def stage(name, fv, began, certified, j=None):
        rec['stages'].append(dict(stage=name, fv_solves=fv, seconds=time.perf_counter() - began, certified=certified,
                                  wire_ok_j_k=j))
        rec['fv_solves'] += fv
        ctx['fv'] += fv

    if time.perf_counter() < deadline and ctx['fv_budget'] - ctx['fv'] > 1:
        began = time.perf_counter()
        moved = centred(base, base_um, sized.carrier_um) if w*1000 >= base_um[0] and h*1000 >= base_um[1] else None
        if moved is not None and is_legal(sized, moved, ctx['gap_um']) and time.perf_counter() < deadline:
            starts.append(moved)
            ok, (j, l), n = certify(sized, moved, ctx['gap_um'], L, 0, ctx['resolution'])
            stage('move', n, began, ok is not None, j if l <= L + 1e-9 else None)
        if ok is None and time.perf_counter() < deadline:
            began = time.perf_counter()
            mapped = fit_into(sized, base, base_um, ctx['gap_um'])
            if mapped is not None:
                starts.append(mapped)
                steps = min(REPAIR_FV, ctx['fv_budget'] - ctx['fv']) - 1
                if steps >= 0 and time.perf_counter() < deadline:
                    ok, (j, l), n = certify(sized, mapped, ctx['gap_um'], L, steps, ctx['resolution'])
                    stage('repair', n, began, ok is not None, j if l <= L + 1e-9 else None)
            else:
                stage('repair', 0, began, False)
    if ok is None and ctx.get('v8') and time.perf_counter() < deadline and ctx['fv_budget'] - ctx['fv'] > 1:
        began = time.perf_counter()                      # the parent's binding chain: flip links, LP, repair
        flipped, flips = chain_flip(sized, base, ctx['gap_um'])
        if flipped is not None and time.perf_counter() < deadline:
            starts.append(flipped)
            steps = min(REPAIR_FV, ctx['fv_budget'] - ctx['fv']) - 1
            ok, (j, l), n = certify(sized, flipped, ctx['gap_um'], L, steps, ctx['resolution'])
            stage('chain_flip', n, began, ok is not None, j if l <= L + 1e-9 else None)
            rec['stages'][-1]['flips'] = flips
        else:
            stage('chain_flip', 0, began, False)
            rec['stages'][-1]['flips'] = flips
    if ok is None and ctx.get('v8') and time.perf_counter() < deadline and ctx['fv_budget'] - ctx['fv'] > 1:
        from .cosize import fixed_carrier                 # the min-wire MILP topology (v6/v3.2 blind's generator)
        began = time.perf_counter()
        layout, statuses, proof, _ = fixed_carrier(sized, ctx['gap_um'], L, None, starts[0] if starts else None,
                                                   max(1.0, min(MILP_S, deadline - time.perf_counter())),
                                                   ctx['threads'], None)
        legal = None if layout is None else legalize_relations(sized, layout, ctx['gap_um'])
        n, j = 0, None
        if legal is not None and is_legal(sized, legal, ctx['gap_um']) and time.perf_counter() < deadline:
            starts.append(legal)
            steps = min(REPAIR_FV, ctx['fv_budget'] - ctx['fv']) - 1
            ok, (jj, l), n = certify(sized, legal, ctx['gap_um'], L, steps, ctx['resolution'])
            j = jj if l <= L + 1e-9 else None
        stage('milp_wire', n, began, ok is not None, j)
        rec['stages'][-1]['solver'] = statuses
        if proof:
            rec['proof'] = proof                         # geometry + wire relaxation: holds for smaller boxes too
    if ok is None and not rec.get('proof') and time.perf_counter() < deadline:
        budget = min(RS_FV, ctx['fv_budget'] - ctx['fv'])
        began = time.perf_counter()
        if budget > 1:
            try:
                rows, archive = relation_front(sized, ctx['gap_um'], budget, shape['rng'], starts,
                                               dict(milp_s=max(1.0, min(60.0, deadline - time.perf_counter())),
                                                    workers=ctx['workers'], resolution=ctx['resolution']))
            except NoLegalStart:
                rows, archive = [], dict(solves=0)
            within = [i for i, r in enumerate(rows) if r['length_m'] <= L + 1e-9]
            good = [i for i in within if rows[i]['thermal'] <= 0]
            if good:
                i = min(good, key=lambda i: (rows[i]['thermal'], rows[i]['length_m'], i))
                ok = (Layout(np.asarray(archive['centre_um'][i]), np.asarray(archive['rotation_deg'][i])),
                      rows[i]['thermal'], rows[i]['length_m'])
            stage('relation_space', int(archive['solves']), began, ok is not None,
                  min((rows[i]['thermal'] for i in within), default=None))
    if ok is not None and time.perf_counter() > deadline:
        rec['after_deadline'], ok = True, None
        for st in rec['stages']:
            st['certified'] = False                      # not accepted: no stage is credited
    rec['certified'] = ok is not None
    rec['first_certifier'] = next((s['stage'] for s in rec['stages'] if s['certified']), None) if ok else None
    rec['elapsed_s'], rec['fv_total'] = time.perf_counter() - ctx['started'], ctx['fv']
    if ok is not None:
        rec.update(j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(),
                   rotation_deg=ok[0].rotation_deg.tolist())
    return rec, ok


def joint_search(ctx, deadline):
    """The free-shape joint sizing MILP (portfolio.joint_arm) with what is left: one call of at most JOINT_S."""
    from .portfolio import joint_arm
    left_s = min(JOINT_S, deadline - time.perf_counter())
    budget = ctx['fv_budget'] - ctx['fv']
    if left_s < 2 or budget <= 1 or ctx['model'] is None:
        return []
    gen = joint_arm(ctx, 'joint')
    next(gen)
    recs = gen.send((budget, left_s))
    used = sum(x.get('fv_solves', 0) for x in recs if 'centre_um' not in x)
    ctx['fv'] += used
    if time.perf_counter() > deadline:
        for x in recs:
            if x.get('certified'):
                x['certified'], x['after_deadline'] = False, True
    return recs


def scheduled(problem, anchor, gap_um, length_m, fv_budget=1000, deadline=None, envelope=1.25, resolution=64,
              chain_steps=12, threads=16, workers=16, seed=2, params=CostParams(), expected_j_k=0.0, v8=False):
    """cosize v7 (module docstring). `deadline` is an absolute time.perf_counter() value shared with the baseline."""
    deadline = math.inf if deadline is None else deadline
    out = dict(best=None, history=[], fv_solves=0, calibration_solves=0, anchor=None, inner='v8' if v8 else 'v7')
    if fv_budget < 1 or time.perf_counter() >= deadline:
        out['history'].append(dict(stop='fv budget or deadline before the anchor check'))
        return out
    check = verify_anchor(problem, anchor, gap_um, length_m, resolution, expected_j_k)
    out.update(anchor=check, fv_solves=1)
    if not check['ok']:
        out['history'].append(dict(stop='reproduction_mismatch'))
        return out
    w0, h0 = (s/1000 for s in problem.carrier_um)
    c0 = interposer_cost(w0, h0, params)
    pool = [] if not math.isfinite(c0['total_usd']) else [dict(arm='anchor', width_mm=w0, height_mm=h0,
            cost_usd=c0['total_usd'], certified=True, j_k=check['j_k'], length_m=check['length_m'],
            centre_um=anchor.centre_um.tolist(), rotation_deg=anchor.rotation_deg.tolist())]
    ctx = dict(problem=problem, anchor=anchor, gap_um=gap_um, length_m=length_m, params=params, seed=seed,
               workers=workers, threads=threads, resolution=resolution, chain_steps=chain_steps, fv=1,
               fv_budget=fv_budget, started=time.perf_counter(), model=None, joint_margin=0.0, v8=v8)
    die_area = float(problem.size_um.prod(axis=1).sum())/1e6
    shapes = []
    for k, a in enumerate([w0/h0] + [a for a in SHAPES if abs(math.log(a*h0/w0)) > math.log(1.05)]):
        high = area_ceiling(a, die_area, w0*h0*envelope**2, c0['total_usd'], params)
        if high is None:
            out['history'].append(dict(aspect=a, stop='no carrier cheaper than the anchor'))
            continue
        shapes.append(dict(aspect=a, hi=high, lo=die_area, queue=[(die_area + high)/2], tried=set(), targets=0, base=anchor,
                           base_um=problem.carrier_um, rng=np.random.default_rng([seed, k]), certified_hi=None))
    while shapes and time.perf_counter() < deadline and fv_budget - ctx['fv'] > 1:
        progressed = False
        for s in shapes:
            if not s['queue'] or s['targets'] >= TARGETS or time.perf_counter() >= deadline or fv_budget - ctx['fv'] <= 1:
                continue
            area = s['queue'].pop(0)
            size = box(area, s['aspect'])
            if size in s['tried'] or area <= s['lo'] or (s['certified_hi'] is not None and area >= s['certified_hi']):
                continue                                 # tried, proven out, or no smaller than a certified carrier
            s['tried'].add(size)
            s['targets'] += 1
            progressed = True
            rec, ok = cascade(ctx, s, area, deadline)
            out['history'].append(rec)
            ref = s['certified_hi'] if s['certified_hi'] is not None else s['hi']
            if ok is not None:
                pool.append(dict(rec, arm=f"{rec['first_certifier']}:{s['aspect']:.3f}"))
                if s['certified_hi'] is None or area < s['certified_hi']:   # only a smaller parent replaces one
                    s['certified_hi'], s['base'] = area, ok[0]
                    s['base_um'] = (rec['width_mm']*1000, rec['height_mm']*1000)
                s['queue'].insert(0, (s['lo'] + s['certified_hi'])/2)
            elif rec.get('proof'):                       # proven: this box and smaller ones of the shape are out
                s['lo'] = max(s['lo'], area)
                s['queue'] = [a for a in s['queue'] if a > s['lo']]
                if area < ref:
                    s['queue'].insert(0, (area + ref)/2)
            else:                                        # not a proof: both halves stay queued, in turn
                if area < ref:
                    s['queue'].append((area + ref)/2)
                s['queue'].append((s['lo'] + area)/2)
        if not progressed:
            break
    if time.perf_counter() < deadline and fv_budget - ctx['fv'] > 1 and \
            fv_budget - ctx['fv'] >= len(R_MM) + len({tuple(x) for x in problem.size_um}) + 2:
        model = ThermalProxy.calibrate(problem, gap_um, resolution)
        ctx['fv'] += model.solves
        out['calibration_solves'] = model.solves
        ctx.update(model=model, joint_margin=-(model.envelope_value(problem, anchor, gap_um) - check['j_k']))
        joint = joint_search(ctx, deadline)
        out['history'] += joint
        pool += [x for x in joint if x.get('certified') and 'centre_um' in x]
    out['fv_solves'] = ctx['fv']
    if pool:
        best = min(pool, key=lambda x: x['cost_usd'])
        c = interposer_cost(best['width_mm'], best['height_mm'], params)
        out['best'] = dict(best, option=c['option'], fields=c['fields'], anchor=best['arm'] == 'anchor')
    out['search_wall_s'] = time.perf_counter() - ctx['started']
    return out
