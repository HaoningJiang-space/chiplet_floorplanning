"""Interposer size and reticle option co-optimised with placement (plan: docs/cosize-v3-plan.md, protocol v3.1).

Problem: the cheapest interposer (cost.interposer_cost) that carries a legal layout with every die within its
absolute limit (Problem.limit_c, FV) and exact pin length within a budget. The reference layout (ATPlace's, on the
original carrier) is a known feasible anchor, re-checked by one FV solve. Per aspect family, trial carriers from the
largest cheaper one down: each is seeded with the smallest certified layout so far (mapped and legalised), and a
MILP on the fixed carrier proposes a new topology when that fails; every candidate is certified by an exact FV SLP
chain. Only FV-certified layouts are reported; the proxy never certifies anything. The earlier joint sizing MILP
(cosize-v1/v2) was removed after commit 33ad191; replay it at that commit.
"""
from dataclasses import replace
import math

import numpy as np

from .cost import CostParams, interposer_cost
from .geometry import is_legal, pin_manhattan_um
from .lp import MILP_STATUS, legalize_relations, milp_relations, slp_chain
from .proxy import R_MM, ThermalProxy

GRID_MM = 0.1          # carrier dimensions are rounded up to this grid


def ceil_grid(value_mm):
    return math.ceil(value_mm/GRID_MM - 1e-6)*GRID_MM


def certify(problem, layout, gap_um, length_m, steps, resolution):
    """Exact SLP chain (min J within the length budget). Returns (best certified (layout, J, length) or None,
    best (J, length) seen, FV solves)."""
    chain = slp_chain((problem, layout, gap_um, resolution, length_m, steps, 'length'))
    rows = [(l, float(p.max()), pin_manhattan_um(problem, l).sum()/1e6) for l, p in chain]
    ok = [r for r in rows if r[1] <= 0 and r[2] <= length_m + 1e-9]
    within = [r for r in rows if r[2] <= length_m + 1e-9]
    seen = min(within or rows, key=lambda r: r[1])
    return (min(ok, key=lambda r: r[1]) if ok else None), (seen[1], seen[2]), len(chain)


ASPECTS = (1/3, 1/2, 2/3, 1.0, 3/2, 2.0, 3.0)
REPRODUCE_K, REPRODUCE_M = 1e-6, 1e-9
EVEN = (0.0, 0.25, 0.5, 0.75)   # trial areas: high - f (high - low), plus the carriers just below each cost step
MAX_TRIALS, REFINE = 8, 2


def box(area_mm2, aspect):
    """Grid-rounded carrier of about this area with width/height = aspect."""
    return ceil_grid(math.sqrt(area_mm2*aspect)), ceil_grid(math.sqrt(area_mm2/aspect))


def area_ceiling(aspect, low, high, cap_usd, params, points=400):
    """Largest area on a fine grid in [low, high] below which every carrier of this aspect costs < cap_usd
    (finite when cap_usd is inf); None if even the smallest does not."""
    best = None
    for a in np.linspace(low, high, points):
        if not interposer_cost(*box(a, aspect), params)['total_usd'] < cap_usd:
            break
        best = float(a)
    return best


def trial_areas(aspect, low, high, params, points=400, step=0.02):
    """Descending trial areas of one family: evenly spaced ones and, from the cost curve itself, the largest area
    before each cost step of more than `step` (exposure fields, substrate tiers); at most MAX_TRIALS, the largest
    first. A finite candidate list, not a feasibility boundary."""
    grid = np.linspace(low, high, points)
    cost = np.array([interposer_cost(*box(a, aspect), params)['total_usd'] for a in grid])
    steps = [float(grid[i]) for i in range(points - 1) if cost[i + 1] > cost[i]*(1 + step)]
    areas = sorted({round(high - f*(high - low), 6) for f in EVEN} | {round(a, 6) for a in steps}, reverse=True)
    return [a for a in areas if a > low][:MAX_TRIALS]


def fit_into(problem, layout, source_um, gap_um):
    """The layout's centres mapped proportionally from its carrier (source_um) into problem's, legalised keeping the
    side relations; None if they do not fit."""
    scaled = replace(layout, centre_um=layout.centre_um*np.asarray(problem.carrier_um)/np.asarray(source_um))
    return legalize_relations(problem, scaled, gap_um)


def verify_anchor(problem, anchor, gap_um, length_m, resolution):
    """One FV solve of the reference layout on its own carrier: legality, exact pin length and every die's
    overshoot J against problem.limit_c. Shared by every method; ok only if the declared limits reproduce."""
    (_, peaks), = slp_chain((problem, anchor, gap_um, resolution, length_m, 0, 'length'))
    j, length = float(peaks.max()), pin_manhattan_um(problem, anchor).sum()/1e6
    check = dict(j_k=j, die_j_k=np.asarray(peaks, float).tolist(), length_m=length,
                 legal=bool(is_legal(problem, anchor, gap_um)), carrier_mm=[s/1000 for s in problem.carrier_um])
    check['ok'] = check['legal'] and abs(j) <= REPRODUCE_K and length <= length_m + REPRODUCE_M
    return check


def fixed_carrier(problem, gap_um, length_m, model, start, time_s, threads, directions, max_cuts=3):
    """MILP topology candidate on one carrier: min the proxy (model; wire-only without it) with the clustered wire
    within the budget, pin-length cuts on overshoot; axial first, then K directions warm-started by it. All calls
    share `time_s`. Returns (layout or None, statuses, 'proven_infeasible' | None, MILP seconds). Infeasible is a
    proof for the carrier: the rows are geometry, the clustered-wire relaxation and valid pin cuts only."""
    import time
    wire_mm, cuts, statuses, out, began = length_m*1000, [], [], None, time.perf_counter()
    left = lambda: time_s - (time.perf_counter() - began)   # noqa: E731
    for _ in range(max_cuts + 1):
        if left() < 1:
            break
        proxy = None if model is None else (model, None, wire_mm)
        found = milp_relations(problem, gap_um, left(), proxy=proxy, wire_mm=wire_mm, threads=threads, focus=1,
                               wire_cuts=cuts, start=start)
        statuses.append(MILP_STATUS['status'])
        # Gurobi's INF_OR_UNBD ('4') is infeasible here: the objective (proxy or wire) is bounded below.
        if found is None and statuses[-1] in ('infeasible', '4'):
            return None, statuses, 'proven_infeasible', time.perf_counter() - began
        if model is not None and directions and found is not None and left() >= 1:
            polygon = milp_relations(problem, gap_um, left(), proxy=proxy, wire_mm=wire_mm, threads=threads, focus=1,
                                     wire_cuts=cuts, directions=directions, start=found)
            statuses.append(MILP_STATUS['status'])
            found = polygon or found
        if found is None:
            break
        out = found
        if pin_manhattan_um(problem, found).sum()/1000 <= wire_mm + 1e-6:
            break
        cuts.append(found)
    return out, statuses, None, time.perf_counter() - began


def try_carrier(sized, base, base_um, gap_um, length_m, model, budget, size_s, threads, directions, resolution,
                chain_steps, seed, workers, rs_share=None):
    """One trial carrier. Candidates in order, each FV-certified within `budget`: (1) the last certified layout
    mapped into this carrier (keeps its topology; the SLP chain is the local thermal/length repair), (2) a new
    topology - the MILP (model given or 'blind'), or relation_space seeded with (1) (model == 'relation_space').
    relation_space spends at most `rs_share` FV solves per trial (it would otherwise use the whole family budget on
    the first trial). Returns (record fields, certified (layout, J, length) or None, FV solves)."""
    start = fit_into(sized, base, base_um, gap_um)
    rec, used, ok = dict(started=start is not None, stages=[]), 0, None
    if start is not None and budget - used > 1:
        ok, (j, l), n = certify(sized, start, gap_um, length_m, min(chain_steps, budget - used - 1), resolution)
        used += n
        rec['stages'].append(dict(stage='start', fv_solves=n, best_j_k=j, best_length_m=l, certified=ok is not None))
    if ok is None and budget - used > 1:
        if model == 'relation_space':
            from run_sizing import run_front              # tools/: the size-then-place baseline's inner search
            import time
            began = time.perf_counter()
            try:
                rows, archive = run_front(sized, gap_um, min(budget - used, rs_share or budget), seed, [start],
                                          dict(milp_s=size_s, workers=workers))
            except RuntimeError:                  # no legal start (raised before any FV solve)
                rows, archive = [], dict(solves=0)
            n = int(archive['solves'])
            good = [i for i, r in enumerate(rows) if r['thermal'] <= 0 and r['length_m'] <= length_m + 1e-9]
            if good:
                i = min(good, key=lambda i: (rows[i]['thermal'], rows[i]['length_m'], i))
                from .problem import Layout
                ok = (Layout(archive['centre_um'][i], archive['rotation_deg'][i]), rows[i]['thermal'], rows[i]['length_m'])
            used += n
            rec['stages'].append(dict(stage='relation_space', fv_solves=n, certified=ok is not None,
                                      seconds=time.perf_counter() - began))
        else:
            layout, statuses, proof, secs = fixed_carrier(sized, gap_um, length_m, None if model == 'blind' else model,
                                                          start, size_s, threads, directions)
            stage = dict(stage='milp', solver=statuses, milp_s=secs)
            if proof:
                rec['proof'] = stage['proof'] = proof
            legal = None if layout is None else legalize_relations(sized, layout, gap_um)
            if legal is not None and is_legal(sized, legal, gap_um) and budget - used > 1:
                ok, (j, l), n = certify(sized, legal, gap_um, length_m, min(chain_steps, budget - used - 1), resolution)
                used += n
                stage.update(fv_solves=n, best_j_k=j, best_length_m=l)
            stage['certified'] = ok is not None
            rec['stages'].append(stage)
    rec['status'] = 'certified' if ok is not None else rec.get('proof', 'not_found')
    return rec, ok, used


def family(args):
    """One aspect family: the trial areas from the largest down, each trial seeded with the smallest certified
    layout so far (continuation); a failure is recorded and the search goes on - only a proof of infeasibility ends
    it (smaller carriers of this aspect fit inside, so they are infeasible too). Then up to REFINE bisections
    between the smallest certified area and the next failed one (or the dies' total area if none failed). Returns the records and FV solves."""
    (problem, anchor, gap_um, length_m, model, aspect, low, high, budget, size_s, threads, directions, resolution,
     chain_steps, params, seed, workers) = args
    base, base_um, used, records = anchor, problem.carrier_um, 0, []
    good = None                                         # smallest certified area
    areas = trial_areas(aspect, low, high, params)
    rs_share = max(2, budget//(len(areas) + REFINE))     # relation_space: an equal share per planned trial

    def trial(area, step):
        nonlocal base, base_um, used, good
        w, h = box(area, aspect)
        sized = replace(problem, carrier_um=(w*1000, h*1000))
        rec, ok, n = try_carrier(sized, base, base_um, gap_um, length_m, model, budget - used, size_s, threads,
                                 directions, resolution, chain_steps, seed, workers, rs_share)
        used += n
        rec.update(aspect=aspect, step=step, area_mm2=area, width_mm=w, height_mm=h, fv_solves=n,
                   cost_usd=interposer_cost(w, h, params)['total_usd'], certified=ok is not None)
        if ok is not None:
            rec.update(j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(),
                       rotation_deg=ok[0].rotation_deg.tolist())
            base, base_um = ok[0], sized.carrier_um
            if good is None or area < good:
                good = area
        records.append(rec)
        return rec

    step = 0
    for area in areas:
        if budget - used <= 1:
            records.append(dict(aspect=aspect, step=step, stop='fv budget'))
            return records, used
        rec = trial(area, step)
        step += 1
        if rec['status'] == 'proven_infeasible':
            records.append(dict(aspect=aspect, step=step, stop='proven infeasible below'))
            break
    failed = [r['area_mm2'] for r in records if r.get('status') in ('not_found', 'proven_infeasible') and good is not None
              and r['area_mm2'] < good]
    hi_ok, lo_bad = good, max(failed) if failed else low     # all certified: refine toward the dies' total area
    for _ in range(REFINE):
        if hi_ok is None or lo_bad is None or budget - used <= 1:
            break
        area = (hi_ok + lo_bad)/2
        rec = trial(area, step)
        step += 1
        if rec['certified']:
            hi_ok = area
        else:
            lo_bad = area
    return records, used


def anchored(problem, anchor, gap_um, length_m, fv_budget, inner='proxy', directions=8, aspects=ASPECTS,
             envelope=1.25, size_s=120.0, threads=2, workers=8, resolution=64, chain_steps=12, params=CostParams(),
             seed=2):
    """cosize v3.1 (docs/cosize-v3-plan.md). `anchor` is the reference layout on problem's own carrier, expected to
    meet both limits (problem.limit_c = its FV peak, length_m = its pin length); verify_anchor re-checks it (1 FV).
    Per aspect family (ASPECTS plus the original) the trial carriers cheaper than the anchor's (or manufacturable,
    if that is not) are searched by `family`; every trial is FV-certified. inner: 'proxy' (K-direction MILP),
    'axial', 'blind' (min-wire MILP) or 'relation_space' (control: the baseline's inner search on the same trials;
    families then run one after another, the FV evaluator using `workers`). The FV budget covers the anchor check
    and the calibration. Returns the cheapest certified design (the anchor if nothing beats it) and every record."""
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    if problem.limit_c is None:
        raise ValueError('anchored needs absolute per-die limits (Problem.limit_c)')
    out = dict(best=None, history=[], fv_solves=0, calibration_solves=0, anchor=None, inner=inner)
    if fv_budget < 1:
        out['history'].append(dict(stop='fv budget before the anchor check'))
        return out
    check = verify_anchor(problem, anchor, gap_um, length_m, resolution)
    out.update(anchor=check, fv_solves=1)
    if not check['ok']:
        out['history'].append(dict(stop='reproduction_mismatch'))
        return out
    w0, h0 = (s/1000 for s in problem.carrier_um)
    c0 = interposer_cost(w0, h0, params)
    if math.isfinite(c0['total_usd']):
        out['best'] = dict(width_mm=w0, height_mm=h0, cost_usd=c0['total_usd'], option=c0['option'],
                           fields=c0['fields'], j_k=check['j_k'], length_m=check['length_m'],
                           centre_um=anchor.centre_um.tolist(), rotation_deg=anchor.rotation_deg.tolist(), anchor=True)
    model = inner
    if inner in ('proxy', 'axial'):
        if fv_budget - out['fv_solves'] < len(R_MM) + len({tuple(s) for s in problem.size_um}):
            out['history'].append(dict(stop='fv budget before calibration'))
            return out
        model = ThermalProxy.calibrate(problem, gap_um, resolution)
        out['fv_solves'] += model.solves
        out['calibration_solves'] = model.solves
    die_area = float(problem.size_um.prod(axis=1).sum())/1e6
    fams = sorted(set(aspects) | {w0/h0})
    share = (fv_budget - out['fv_solves'])//len(fams)
    jobs = []
    for aspect in fams:
        high = area_ceiling(aspect, die_area, w0*h0*envelope**2, c0['total_usd'], params)
        if high is None or share < 2:
            out['history'].append(dict(aspect=aspect, stop='no carrier cheaper than the anchor' if high is None
                                       else 'fv budget'))
            continue
        jobs.append((problem, anchor, gap_um, length_m, model, aspect, die_area, high, share, size_s, threads,
                     directions if inner == 'proxy' else None, resolution, chain_steps, params, seed, workers))
    if workers > 1 and len(jobs) > 1 and inner != 'relation_space':
        with ProcessPoolExecutor(min(workers, len(jobs)), mp_context=multiprocessing.get_context('spawn')) as pool:
            results = list(pool.map(family, jobs))
    else:
        results = [family(j) for j in jobs]
    best = out['best']
    for records, used in results:
        out['history'] += records
        out['fv_solves'] += used
        for r in records:
            if r.get('certified') and math.isfinite(r['cost_usd']) and (best is None or r['cost_usd'] < best['cost_usd']):
                c = interposer_cost(r['width_mm'], r['height_mm'], params)
                best = dict(width_mm=r['width_mm'], height_mm=r['height_mm'], cost_usd=r['cost_usd'], option=c['option'],
                            fields=c['fields'], j_k=r['j_k'], length_m=r['length_m'], centre_um=r['centre_um'],
                            rotation_deg=r['rotation_deg'], aspect=r['aspect'], step=r['step'], anchor=False)
    out['best'] = best
    return out
