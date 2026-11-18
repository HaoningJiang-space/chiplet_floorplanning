"""Certified carrier sizing with a per-shape target queue and a shared FV and wall budget.
The cascade tries a rigid move, proportional repair, chain flip, min-wire MILP, then relation-space search.
Only a solver proof raises a shape's lower bound. Free rectangles enter the global pool independently.
"""
from dataclasses import replace
import math
import time

import numpy as np

from .cosize import area_ceiling, box, ceil_grid, certify, crop_candidate, fit_into, verify_anchor
from .cost import CostParams, interposer_cost, max_height
from .geometry import is_legal
from .lp import MILP_STATUS, TopologyLP, legalize_relations, milp_relations, topology
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
    return lp.shortest_layout(), flips


def cascade(ctx, shape, area, deadline):
    """Try one target carrier of `shape`: unscaled move, else mapping + SLP repair, then the chain flip and
    the min-wire MILP generator; then relation_space (skipped once the MILP proves the box infeasible). Returns the
    target record (each stage: executed, FV, seconds, certified, wire-feasible overshoot) and the certified
    (layout, J, length) or None."""
    from .methods import NoLegalStart, relation_front
    w, h = box(area, shape['aspect'])
    dims_um = (round(w*1000), round(h*1000)) if ctx.get('rectangles') else (w*1000, h*1000)
    sized = replace(ctx['problem'], carrier_um=dims_um)
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
        if ctx.get('rectangles'):
            # Grid carriers have integral µm sides. Remove floating-point noise before translating touching dies.
            moved = centred(base, np.round(base_um, 8), dims_um)
        else:
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
    if ok is None and time.perf_counter() < deadline and ctx['fv_budget'] - ctx['fv'] > 1:
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
    if ok is None and time.perf_counter() < deadline and ctx['fv_budget'] - ctx['fv'] > 1:
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


def crop_parent(ctx, parent, layout, arm, j_k, cost_cap, deadline):
    if ctx['best_crop'] is not None:
        cost_cap = min(cost_cap, ctx['best_crop']['cost_usd'])
    rec = crop_candidate(parent, layout, ctx['gap_um'], ctx['length_m'], arm, j_k, cost_cap, ctx['fv'],
                         ctx['fv_budget'], deadline, ctx['resolution'], ctx['params'])
    ctx['fv'] += rec['fv_solves']
    rec['elapsed_s'] = time.perf_counter() - ctx['started']
    if rec['certified']:
        ctx['best_crop'] = rec
    return rec


def refine_rectangle(ctx, parent, layout, cost_cap, deadline):
    """Query one grid endpoint per axis of a certified parent. Only FV-certified improvements enter the pool."""
    records = []
    dims_mm = [v/1000 for v in parent.carrier_um]
    # The fixed side is also a grid choice. Build the LP on an envelope containing both rounded sides.
    upper_um = tuple(round(ceil_grid(v)*1000) for v in dims_mm)
    envelope = replace(parent, carrier_um=upper_um)
    gap, length = ctx['gap_um'], ctx['length_m']
    if ctx['fv'] >= ctx['fv_budget'] or time.perf_counter() >= deadline:
        return records
    relations = topology(parent, layout, gap)
    extent_mm, _ = min_extent(parent, layout, relations, gap)
    # With one side fixed, both the longest chain and the 3:1 limit bound the other before any wire LP.
    aspect_floor_mm = [side_um/1000/3 for side_um in reversed(upper_um)]
    axes = [a for a, span in enumerate(extent_mm)
            if round(ceil_grid(max(span, aspect_floor_mm[a]))*1000) < upper_um[a]]
    if not axes:
        return records
    lp = TopologyLP(envelope, layout, gap, pairs=0, relations=relations)
    for axis in axes:
        if ctx['fv'] >= ctx['fv_budget'] or time.perf_counter() >= deadline:
            break
        span = lp.minimum_span_mm(axis, length)
        if span is None:
            continue
        target = list(upper_um)
        fixed_mm = target[1-axis]/1000
        span_mm = ceil_grid(max(span, aspect_floor_mm[axis]))
        target[axis] = round(span_mm*1000)
        if target[axis] >= upper_um[axis] or span_mm > 3*fixed_mm + 1e-9:
            continue
        w, h = (s/1000 for s in target)
        cost = interposer_cost(w, h, ctx['params'])['total_usd']
        if cost >= cost_cap or time.perf_counter() >= deadline:
            continue
        sized = replace(parent, carrier_um=tuple(target))
        seed = TopologyLP(sized, layout, gap, pairs=0, relations=relations).shortest_layout()
        rec = dict(arm='rectangle_lp', axis=('width', 'height')[axis], parent_mm=dims_mm,
                   width_mm=w, height_mm=h, cost_usd=cost, minimum_span_mm=span, certified=False, fv_solves=0)
        if seed is not None and time.perf_counter() < deadline:
            steps = min(ctx['chain_steps'], ctx['fv_budget'] - ctx['fv'] - 1)
            ok, _, used = certify(sized, seed, gap, length, steps, ctx['resolution'])
            ctx['fv'] += used
            rec['fv_solves'] = used
            if time.perf_counter() > deadline:
                rec['after_deadline'] = True
            elif ok is not None:
                rec.update(certified=True, j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(),
                           rotation_deg=ok[0].rotation_deg.tolist())
                cost_cap = cost
        rec.update(fv_total=ctx['fv'], elapsed_s=time.perf_counter() - ctx['started'])
        records.append(rec)
        if rec['certified'] and ctx.get('online_crop'):
            records.append(crop_parent(ctx, sized, ok[0], 'rectangle_lp', ok[1], cost_cap, deadline))
    return records


def joint_search(ctx, deadline):
    """Search the free-width and height MILP over the remaining wall and FV budget."""
    left_s = min(JOINT_S, deadline - time.perf_counter())
    budget = ctx['fv_budget'] - ctx['fv']
    if left_s < 2 or budget <= 1 or ctx['model'] is None:
        return []
    p, gap = ctx['problem'], ctx['gap_um']
    w_max, h_max = (s/1000*1.25 for s in p.carrier_um)
    envelope = replace(p, carrier_um=(w_max*1000, h_max*1000))
    narrow = p.size_um.min(axis=1).max()/1000
    levels = np.arange(math.ceil(narrow/0.5)*0.5, w_max + 1e-9, 0.5)
    model, margin = ctx['model'], ctx['joint_margin']
    out, used, began = [], 0, time.perf_counter()
    found = []
    for k in (1, 2, 3, 4):
        left = left_s - (time.perf_counter() - began)
        if left < 2:
            break
        caps = np.array([min(max_height(w, k, h_max, ctx['params']), 3.0*w) for w in levels])
        excluded = [l for l, w in enumerate(levels) if caps[l] < w/3.0]
        if len(excluded) == len(levels):
            continue
        sizing = (levels, None, excluded, caps, True, levels/3.0)
        res = milp_relations(envelope, gap, left/2, sizing=sizing, proxy=(model, -margin, ctx['length_m']*1000),
                             threads=ctx['threads'], focus=1)
        out.append(dict(arm='joint', fields=k, solver=MILP_STATUS['status'], margin_k=margin))
        if res is None:
            continue
        layout, extent, _ = res
        w, h = (ceil_grid(v) for v in extent)
        w, h = max(w, ceil_grid(h/3.0)), max(h, ceil_grid(w/3.0))
        cost = interposer_cost(w, h, ctx['params'])['total_usd']
        if math.isfinite(cost):
            found.append((cost, w, h, layout))
    for cost, w, h, layout in sorted(found, key=lambda f: f[0]):
        if budget - used <= 1 or time.perf_counter() >= deadline:
            break
        sized = replace(p, carrier_um=(w*1000, h*1000))
        legal = legalize_relations(sized, layout, gap)
        if legal is None or not is_legal(sized, legal, gap) or time.perf_counter() >= deadline:
            continue
        ok, (j, l), n = certify(sized, legal, gap, ctx['length_m'], min(ctx['chain_steps'], budget - used - 1),
                                ctx['resolution'])
        used += n
        out.append(dict(arm='joint', width_mm=w, height_mm=h, cost_usd=cost, fv_solves=n, certified=ok is not None,
                        best_j_k=j, wire_ok_j_k=j if l <= ctx['length_m'] + 1e-9 else None))
        if ok is not None:
            out.append(dict(arm='joint', width_mm=w, height_mm=h, cost_usd=cost, certified=True,
                            j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(),
                            rotation_deg=ok[0].rotation_deg.tolist()))
            break
    ctx['fv'] += used
    if time.perf_counter() > deadline:
        for x in out:
            if x.get('certified'):
                x['certified'], x['after_deadline'] = False, True
    return out


def scheduled(problem, anchor, gap_um, length_m, fv_budget=1000, deadline=None, envelope=1.25, resolution=64,
              chain_steps=12, threads=16, workers=16, seed=2, params=CostParams(), expected_j_k=0.0, v8=None,
              online_crop=False):
    """Shared size schedule. `deadline` is an absolute time.perf_counter() value shared with the baseline."""
    if v8 is False:
        raise ValueError('v7 was retired; replay it at 64d899e or omit v8 for the current method')
    if online_crop and v8 is True:
        raise ValueError('online cropping is available with the current rectangle schedule')
    rectangles = v8 is None
    deadline = math.inf if deadline is None else deadline
    out = dict(best=None, history=[], fv_solves=0, calibration_solves=0, anchor=None, inner='rectangles' if rectangles else 'v8')
    if fv_budget < 1 or time.perf_counter() >= deadline:
        out['history'].append(dict(stop='fv budget or deadline before the anchor check'))
        return out
    check = verify_anchor(problem, anchor, gap_um, length_m, resolution, expected_j_k)
    out.update(anchor=check, fv_solves=check['fv_solves'])
    if not check['ok']:
        out['history'].append(dict(stop='reproduction_mismatch'))
        return out
    if time.perf_counter() >= deadline:
        check.update(ok=False, after_deadline=True)
        out['history'].append(dict(stop='deadline'))
        return out
    w0, h0 = (s/1000 for s in problem.carrier_um)
    c0 = interposer_cost(w0, h0, params)
    pool = [] if not math.isfinite(c0['total_usd']) else [dict(arm='anchor', width_mm=w0, height_mm=h0,
            cost_usd=c0['total_usd'], certified=True, j_k=check['j_k'], length_m=check['length_m'],
            centre_um=anchor.centre_um.tolist(), rotation_deg=anchor.rotation_deg.tolist())]
    ctx = dict(problem=problem, anchor=anchor, gap_um=gap_um, length_m=length_m, params=params, seed=seed,
               workers=workers, threads=threads, resolution=resolution, chain_steps=chain_steps, fv=1,
               fv_budget=fv_budget, started=time.perf_counter(), model=None, joint_margin=0.0, rectangles=rectangles,
               online_crop=online_crop, best_crop=None)

    def refine(parent, layout, arm, j_k):
        cap = min((r['cost_usd'] for r in pool), default=math.inf)
        if online_crop:
            out['history'].append(crop_parent(ctx, parent, layout, arm, j_k, cap, deadline))
        trials = refine_rectangle(ctx, parent, layout, cap, deadline)
        out['history'].extend(trials)
        # A cheap crop bounds subsequent rigid moves. A costlier LP parent can still have a cheaper descendant.
        pool.extend(r for r in trials if r['certified'] and r['arm'] == 'rectangle_lp')

    if rectangles:
        refine(problem, anchor, 'anchor', check['j_k'])
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
                arm = f"{rec['first_certifier']}:{s['aspect']:.3f}"
                pool.append(dict(rec, arm=arm))
                if rectangles:
                    refine(replace(problem, carrier_um=tuple(round(v*1000) for v in size)), ok[0], arm, ok[1])
                if s['certified_hi'] is None or area < s['certified_hi']:   # only a smaller parent replaces one
                    s['certified_hi'], s['base'] = area, ok[0]
                    s['base_um'] = (rec['width_mm']*1000, rec['height_mm']*1000)
                    if rectangles:
                        s['base_um'] = tuple(round(v) for v in s['base_um'])
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
        for row in joint:
            if row.get('certified') and 'centre_um' in row:
                pool.append(row)
                if online_crop:
                    parent = replace(problem, carrier_um=(row['width_mm']*1000, row['height_mm']*1000))
                    layout = Layout(np.asarray(row['centre_um']), np.asarray(row['rotation_deg']))
                    cap = min(r['cost_usd'] for r in pool)
                    out['history'].append(crop_parent(ctx, parent, layout, 'joint', row['j_k'], cap, deadline))
    out['fv_solves'] = ctx['fv']
    if ctx['best_crop'] is not None:
        pool.append(ctx['best_crop'])
    if pool:
        best = min(pool, key=lambda x: x['cost_usd'])
        c = interposer_cost(best['width_mm'], best['height_mm'], params)
        out['best'] = dict(best, option=c['option'], fields=c['fields'], anchor=best['arm'] == 'anchor')
    out['search_wall_s'] = time.perf_counter() - ctx['started']
    return out
