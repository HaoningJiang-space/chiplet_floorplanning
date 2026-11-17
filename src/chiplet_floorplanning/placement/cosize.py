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
from scipy import sparse
from scipy.optimize import linprog

from .cost import CostParams, interposer_cost
from .geometry import is_legal, pin_manhattan_um
from .lp import (GRID_UM, MILP_STATUS, SLP_BAND_K, SLP_RADIUS_MM, TopologyLP, legalize_relations, milp_relations,
                 slp_chain)
from .problem import Layout
from .proxy import R_MM, ThermalProxy
from .search import snap

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


SHRINK_DELTA = 0.03    # relative carrier growth of the scale secant: near the step size; a 1% difference amplifies
                       # the ~0.01 K mesh jumps (it overstated the 3-6% response twice on Case6)
SHRINK_BUFFER_K = 0.05  # linearised overshoot target -buffer: the FV peak jumps ~0.01 K as the mesh follows the carrier


def shrink_chain(problem, layout, gap_um, length_m, steps, resolution, budget, cool_steps=6, rounds=4):
    """Trust-region SLP on the carrier scale, from a certified layout on problem's carrier (cosize v4 plan).

    The topology and rotations of `layout` are kept. At each accepted state (W, H) the carrier is parameterised
    afresh as W = kx s, H = ky s with s0 = sqrt(W H), so the model is centred on the carrier actually solved (grid
    rounding drifts the ratio slightly; the drift is recorded in the returned carriers). Each step solves the LP:
    min s over centres and s with the topology's separation rows, every die inside [0, kx s] x [0, ky s], the exact
    inter-die pin length within the budget, and every near-peak die's FV overshoot linearised,
    J_i + grad_i . (c - c0) + h_i (s - s0) <= -buffer. grad comes from the deferred adjoints (rows cached per state);
    h is a forward difference: one FV solve on the carrier grown by SHRINK_DELTA with the dies kept at their
    physical package positions (the carrier is centred in the package, so local centres shift by half the growth;
    with the adjoint's translation-invariant gradient the centre shift adds nothing to the model). The buffer is
    min(SHRINK_BUFFER_K, half the current slack), so a state with no slack is not asked for 0.05 K out of nothing.
    A candidate carrier is rounded up to the grid; its exact pin length is checked first, then an exact FV solve
    must give J <= 0: every kept step is a certified design. An infeasible LP is not retried with a smaller trust
    region (a smaller region is a subset); it ends the round, and a cooling SLP (slp_chain, length mode) on the
    current carrier buys slack, for at most `rounds` rounds.
    Returns (certified [(layout, (w, h), J, length m)], FV solves, final state (layout, carrier um, max J) - the
    coolest certified state reached, cooled or shrunk, for continuation - and the model errors of the FV-checked
    candidates, [(predicted max J, actual max J)])."""
    from .thermal import peak_sensitivity
    if budget < 1:
        return [], 0, (layout, problem.carrier_um, None), []
    n = problem.count
    inside = problem.pin_chip[:, 0] == problem.pin_chip[:, 1]
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
    sized, current = problem, layout
    peaks, gradient = peak_sensitivity(sized, current, gap_um, resolution)
    used, out, slope, known, errors = 1, [], None, {}, []

    def rows_of(dies):
        missing = [i for i in dies if i not in known]
        if missing:
            g = gradient(missing)
            known.update((i, g[i]) for i in missing)
        return np.array([known[i] for i in dies]).reshape(len(dies), n, 2)

    _, smallest, largest = SLP_RADIUS_MM
    for _ in range(rounds):
        radius = SLP_RADIUS_MM[0]
        for _ in range(steps):
            if used + 2 > budget or radius < smallest:
                break
            w, h = (v/1000 for v in sized.carrier_um)
            s0 = math.sqrt(w*h)
            kx, ky = w/s0, h/s0
            if slope is None:                              # forward difference, dies fixed in the package
                grown = replace(sized, carrier_um=(w*(1 + SHRINK_DELTA)*1000, h*(1 + SHRINK_DELTA)*1000))
                moved = replace(current, centre_um=current.centre_um + np.array([w, h])*SHRINK_DELTA*500)
                up, _ = peak_sensitivity(grown, moved, gap_um, resolution)
                used += 1
                slope = (up - peaks)/(s0*SHRINK_DELTA)
            buffer = min(SHRINK_BUFFER_K, 0.5*max(0.0, -float(peaks.max())))
            hot = np.flatnonzero(peaks >= peaks.max() - SLP_BAND_K)
            grad = rows_of(hot.tolist())
            lp = TopologyLP(sized, current, gap_um, pairs=0)
            nv = lp.nvar + 1                               # LP variables, then s
            x0 = current.centre_um.T.ravel()/1000
            box = sparse.lil_matrix((2*n, nv))             # c_i + size_i/2 <= k s
            for axis, k in ((0, kx), (1, ky)):
                for i in range(n):
                    box[axis*n + i, axis*n + i], box[axis*n + i, nv - 1] = 1.0, -k
            heat = np.zeros((hot.size, nv))
            heat[:, :2*n] = np.concatenate([grad[:, :, 0], grad[:, :, 1]], axis=1)
            heat[:, nv - 1] = slope[hot]
            offset = heat[:, :2*n] @ x0 + slope[hot]*s0 - peaks[hot]
            budget_mm = length_m*1000 - pin_manhattan_um(problem, current)[inside].sum()/1000
            rows = sparse.vstack([sparse.hstack([lp.A, sparse.csr_matrix((lp.A.shape[0], 1))]), box.tocsr(),
                                  sparse.csr_matrix(heat), sparse.csr_matrix(np.r_[lp.length, 0.0][None])])
            rhs = np.r_[lp.b, -np.r_[size[:, 0], size[:, 1]]/2, offset - buffer, budget_mm]
            bounds = ([(max(lo, x0[k] - radius), x0[k] + radius) for k, (lo, _) in enumerate(lp.bounds[:2*n])]
                      + lp.bounds[2*n:] + [(max(s0 - radius, 0.0), s0)])
            result = linprog(np.r_[np.zeros(lp.nvar), 1.0], A_ub=rows, b_ub=rhs, bounds=bounds, method='highs')
            if result.status == 2:                         # infeasible: a smaller region cannot help; go cool
                break
            if result.status != 0:
                radius /= 2
                continue
            s = result.x[-1]
            cw, ch = min(ceil_grid(kx*s), w), min(ceil_grid(ky*s), h)
            trial = replace(problem, carrier_um=(cw*1000, ch*1000))
            centre = snap(trial, np.stack((result.x[:n], result.x[n:2*n]), axis=1)*1000, current.rotation_deg, GRID_UM)
            candidate = Layout(centre, current.rotation_deg.copy())
            length = pin_manhattan_um(problem, candidate).sum()/1e6
            if (cw, ch) == (w, h) or length > length_m + 1e-9 or not is_legal(trial, candidate, gap_um):
                radius /= 2
                continue
            new_peaks, new_gradient = peak_sensitivity(trial, candidate, gap_um, resolution)
            used += 1
            z = np.r_[candidate.centre_um.T.ravel()/1000, math.sqrt(cw*ch)]
            predicted = float((heat[:, :2*n] @ z[:-1] + slope[hot]*z[-1] - offset).max())
            errors.append((predicted, float(new_peaks.max())))
            accurate = new_peaks.max() - predicted <= max(SHRINK_BUFFER_K, 0.25*abs(predicted - peaks.max()))
            if new_peaks.max() <= 0:
                sized, current, peaks, gradient, slope = trial, candidate, new_peaks, new_gradient, None
                known.clear()
                out.append((candidate, (cw, ch), float(new_peaks.max()), length))
                radius = min(1.5*radius, largest) if accurate else radius    # grow only on a model that held
            else:
                radius /= 2
        if used + 2 > budget:
            break
        chain = slp_chain((sized, current, gap_um, resolution, length_m, min(cool_steps, budget - used - 2), 'length'))
        used += len(chain)
        within = [(l, p) for l, p in chain[1:] if pin_manhattan_um(problem, l).sum()/1e6 <= length_m + 1e-9]
        cooler = min(within, key=lambda pair: pair[1].max(), default=None)
        if cooler is None or cooler[1].max() > peaks.max() - SHRINK_BUFFER_K:
            break                                          # no slack to buy: shrinking has stalled
        current, slope = cooler[0], None
        peaks, gradient = peak_sensitivity(sized, current, gap_um, resolution)
        known.clear()
        used += 1
    return out, used, (current, sized.carrier_um, float(peaks.max())), errors


def verify_anchor(problem, anchor, gap_um, length_m, resolution, expected_j_k=0.0):
    """One FV solve of the reference layout on its own carrier: legality, exact pin length and every die's
    overshoot J against problem.limit_c. Shared by every method; ok only if the declared limits reproduce, i.e. the
    peak overshoot is expected_j_k (0 when the limit is the anchor's own peak; -delta when it is delta above it)."""
    (_, peaks), = slp_chain((problem, anchor, gap_um, resolution, length_m, 0, 'length'))
    j, length = float(peaks.max()), pin_manhattan_um(problem, anchor).sum()/1e6
    check = dict(j_k=j, die_j_k=np.asarray(peaks, float).tolist(), length_m=length,
                 legal=bool(is_legal(problem, anchor, gap_um)), carrier_mm=[s/1000 for s in problem.carrier_um])
    check.update(expected_j_k=expected_j_k)
    check['ok'] = (check['legal'] and abs(j - expected_j_k) <= REPRODUCE_K and j <= REPRODUCE_K
                   and length <= length_m + REPRODUCE_M)            # reproduces, and is itself within the limits
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
        share = left()/2 if model is not None and directions else left()   # leave the K-direction stage its half
        found = milp_relations(problem, gap_um, share, proxy=proxy, wire_mm=wire_mm, threads=threads, focus=1,
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
    topology - the MILP (model given or 'blind'; a list tries the generators in order, sharing size_s), or
    relation_space seeded with (1) (model == 'relation_space').
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
            from .methods import relation_front           # the size-then-place baseline's inner search
            import time
            began = time.perf_counter()
            try:
                rows, archive = relation_front(sized, gap_um, min(budget - used, rs_share or budget), seed, [start],
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
            order = list(model) if isinstance(model, (list, tuple)) else [model]
            for generator in order:                        # a list: the time is shared, the first certified wins
                if ok is not None or rec.get('proof') or budget - used <= 1:
                    break
                proxy = None if generator == 'blind' else generator
                layout, statuses, proof, secs = fixed_carrier(sized, gap_um, length_m, proxy, start, size_s/len(order),
                                                              threads, directions)
                stage = dict(stage='milp', generator='wire' if proxy is None else 'proxy', solver=statuses,
                             milp_s=secs)
                if proof:                                  # either model relaxes the same geometry and wire rows
                    rec['proof'] = stage['proof'] = proof
                legal = None if layout is None else legalize_relations(sized, layout, gap_um)
                if legal is not None and is_legal(sized, legal, gap_um) and budget - used > 1:
                    ok, (j, l), n = certify(sized, legal, gap_um, length_m, min(chain_steps, budget - used - 1),
                                            resolution)
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


SHRINK_STEPS, MOVES, MOVE_AREA = 12, 2, 0.97
WIRE_TIGHT, THERMAL_TIGHT_K = 0.02, 0.5


def generator_order(problem, layout, length_m, j_k, model):
    """Topology generators for the next move, by the constraint that stopped shrinking (docs/cosize-binding-analysis
    .md): wire within WIRE_TIGHT of the budget -> the min-wire MILP first; thermal slack under THERMAL_TIGHT_K -> the
    proxy MILP first; otherwise (geometry) the min-wire MILP first. The other generator follows."""
    wire_slack = 1 - pin_manhattan_um(problem, layout).sum()/1e6/length_m
    if wire_slack >= WIRE_TIGHT and -j_k < THERMAL_TIGHT_K:
        return [model, 'blind']
    return ['blind', model]


def family_shrink(args):
    """cosize v4.1, one aspect family: the largest carrier cheaper than the anchor's is tried as in v3 (the mapped
    anchor first, then MILP topologies), then shrink_chain compresses it continuously; when it stalls, a topology
    move tries the carrier MOVE_AREA times smaller (mapped final state, then MILP topologies) and shrinking resumes,
    at most MOVES times. The MILP generators are ordered by the constraint that stopped shrinking
    (generator_order); at the entry the min-wire MILP goes first, since the anchor has no slack of either kind.
    Same arguments and records as `family`."""
    (problem, anchor, gap_um, length_m, model, aspect, low, high, budget, size_s, threads, directions, resolution,
     chain_steps, params, seed, workers) = args
    used, records, step = 0, [], 0

    def record(rec, w, h, ok, area, n):
        rec.update(aspect=aspect, step=step, area_mm2=area, width_mm=w, height_mm=h, fv_solves=n,
                   cost_usd=interposer_cost(w, h, params)['total_usd'], certified=ok is not None)
        if ok is not None:
            rec.update(j_k=ok[1], length_m=ok[2], centre_um=ok[0].centre_um.tolist(),
                       rotation_deg=ok[0].rotation_deg.tolist())
        records.append(rec)

    base, base_um, area = anchor, problem.carrier_um, high
    generators = ['blind', model]                       # the anchor has neither thermal nor wire slack
    for move in range(MOVES + 1):
        if budget - used <= 2:
            records.append(dict(aspect=aspect, step=step, stop='fv budget'))
            break
        w, h = box(area, aspect)
        sized = replace(problem, carrier_um=(w*1000, h*1000))
        rec, ok, n = try_carrier(sized, base, base_um, gap_um, length_m, generators, budget - used, size_s, threads,
                                 directions, resolution, chain_steps, seed, workers)
        used += n
        rec['stage'] = 'entry' if move == 0 else 'topology move'
        record(rec, w, h, ok, area, n)
        step += 1
        if ok is None:
            records.append(dict(aspect=aspect, step=step, stop='no certified layout at the trial carrier'))
            break
        base, base_um = ok[0], sized.carrier_um
        chain, n, (base, base_um, final_j), errors = shrink_chain(sized, ok[0], gap_um, length_m, SHRINK_STEPS,
                                                                   resolution, budget - used)
        used += n
        generators = generator_order(problem, base, length_m, ok[1] if final_j is None else final_j, model)
        for k, (layout, (cw, ch), j, length) in enumerate(chain):
            record(dict(status='certified', stage='shrink'), cw, ch, (layout, j, length), cw*ch,
                   n if k == len(chain) - 1 else 0)
            step += 1
        records.append(dict(aspect=aspect, step=step, shrink_fv=n, model_errors=errors, next_generators=[
            'wire' if g == 'blind' else 'proxy' for g in generators]))
        area = MOVE_AREA*base_um[0]*base_um[1]/1e6
        if area <= low:
            break
    return records, used


def anchored(problem, anchor, gap_um, length_m, fv_budget, inner='proxy', directions=8, aspects=ASPECTS,
             envelope=1.25, size_s=120.0, threads=2, workers=8, resolution=64, chain_steps=12, params=CostParams(),
             seed=2, expected_j_k=0.0):
    """cosize v3.1 (docs/cosize-v3-plan.md). `anchor` is the reference layout on problem's own carrier, expected to
    meet both limits (problem.limit_c = its FV peak, length_m = its pin length); verify_anchor re-checks it (1 FV).
    Per aspect family (ASPECTS plus the original) the trial carriers cheaper than the anchor's (or manufacturable,
    if that is not) are searched by `family`; every trial is FV-certified. inner: 'proxy' (K-direction MILP),
    'axial', 'blind' (min-wire MILP) or 'relation_space' (control: the baseline's inner search on the same trials;
    families then run one after another, the FV evaluator using `workers`); 'shrink' is cosize v4 (`family_shrink`:
    continuous carrier-scale SLP with K-direction MILP topology moves, docs/cosize-v4-plan.md). The FV budget covers the anchor check
    and the calibration. Returns the cheapest certified design (the anchor if nothing beats it) and every record."""
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    if problem.limit_c is None:
        raise ValueError('anchored needs absolute per-die limits (Problem.limit_c)')
    out = dict(best=None, history=[], fv_solves=0, calibration_solves=0, anchor=None, inner=inner)
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
    if math.isfinite(c0['total_usd']):
        out['best'] = dict(width_mm=w0, height_mm=h0, cost_usd=c0['total_usd'], option=c0['option'],
                           fields=c0['fields'], j_k=check['j_k'], length_m=check['length_m'],
                           centre_um=anchor.centre_um.tolist(), rotation_deg=anchor.rotation_deg.tolist(), anchor=True)
    model = inner
    if inner in ('proxy', 'axial', 'shrink'):
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
                     directions if inner in ('proxy', 'shrink') else None, resolution, chain_steps, params, seed,
                     workers))
    search = family_shrink if inner == 'shrink' else family
    if workers > 1 and len(jobs) > 1 and inner != 'relation_space':
        with ProcessPoolExecutor(min(workers, len(jobs)), mp_context=multiprocessing.get_context('spawn')) as pool:
            results = list(pool.map(search, jobs))
    else:
        results = [search(j) for j in jobs]
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
