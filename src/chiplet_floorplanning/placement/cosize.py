"""Interposer size and reticle option co-optimised with placement (plan: docs/cosize-plan.md).

Problem: the cheapest interposer (cost.interposer_cost) that carries a legal layout with every die within its
absolute limit (Problem.limit_c, FV) and exact pin length within a budget. Cost grows with area inside one reticle
option (k exposure fields), so per option the cheapest carrier is the smallest one.

Method (`cosize`): one proxy calibration is reused for every carrier size. This is an approximation: the proxy is
set by the package stack and die sizes, and the carrier changes it little (a 6 mm, 1 W die alone: 0.4529 / 0.4556 /
0.4555 K/W self-heating on 10 / 30 / 60 mm carriers, docs/proxy-budget-review.md section 4); every result is still
certified by FV on its own carrier. Each round solves, per reticle option, the sizing MILP that minimises the carrier
area with the axial proxy envelope J <= -margin and the clustered wire within the budget; the cheapest result is
legalised on its own extent and certified by an exact FV SLP chain (min J within the length budget). Success
certifies the cost and tightens the area cap; failure raises the margin by the FV miss (closed loop) or, if only the
length failed, adds an exact pin-length cut. Without a proxy (`thermal=False`, the thermal-blind ablation) the area cap
is bisected instead. Only FV-certified layouts are reported; the proxy never certifies anything.
"""
from dataclasses import replace
import math

import numpy as np

from .cost import CostParams, interposer_cost, max_height
from .geometry import is_legal, pin_manhattan_um
from .lp import MILP_STATUS, legalize_relations, milp_relations, slp_chain
from .proxy import ThermalProxy

STEP_MM = 0.5          # width levels
GRID_MM = 0.1          # carrier dimensions are rounded up to this grid
ASPECT = 3.0           # declared: sides within 1:3 .. 3:1
FIELD_OPTIONS = (1, 2, 3, 4)


def width_levels(problem, width_max_mm):
    narrow = problem.size_um.min(axis=1).max()/1000
    return np.arange(math.ceil(narrow/STEP_MM)*STEP_MM, width_max_mm + 1e-9, STEP_MM)


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


def carrier_of(extent_mm):
    """Carrier on the grid that holds the dies' extent and respects the aspect limit (short side padded)."""
    w, h = (ceil_grid(v) for v in extent_mm)
    return max(w, ceil_grid(h/ASPECT)), max(h, ceil_grid(w/ASPECT))


def sized_milp(problem, envelope_problem, levels, h_max, gap_um, milp_s, params, area_cap, wire_mm, proxy, threads,
               cuts, max_cuts=6):
    """Per reticle option k: the MILP's design under the cap (min area with a proxy, else min wire). The clustered
    wire row is only a relaxation of the exact per-pin length, so a result over the exact budget adds a pin-length
    cut (lp.pin_length_cut, valid for every layout) to the shared list `cuts` and is solved again, at most max_cuts
    times. Returns [(cost, width, height, k, layout)] for the options that gave a finite-cost carrier within budget."""
    found, statuses = [], {}
    for k in FIELD_OPTIONS:
        caps = np.array([min(max_height(w, k, h_max, params), ASPECT*w) for w in levels])
        excluded = [l for l, w in enumerate(levels) if caps[l] < w/ASPECT]     # no height within the aspect limit
        if len(excluded) == len(levels):
            continue
        for _ in range(max_cuts + 1):
            out = milp_relations(envelope_problem, gap_um, milp_s,
                                 sizing=(levels, area_cap, excluded, caps, proxy is not None, levels/ASPECT),
                                 proxy=proxy, wire_mm=wire_mm, threads=threads, focus=1, wire_cuts=cuts)
            statuses[k] = MILP_STATUS['status']
            if out is None or pin_manhattan_um(problem, out[0]).sum()/1000 <= wire_mm + 1e-6:
                break
            cuts.append(out[0])
        else:
            out = None
        if out is None:
            continue
        w, h = carrier_of(out[1])
        cost = interposer_cost(w, h, params)['total_usd']
        if math.isfinite(cost):
            found.append((cost, w, h, k, out[0]))
    return found, statuses


def cosize(problem, gap_um, length_m, fv_budget, thermal=True, envelope=1.25, rounds=24, milp_s=120.0, steps=12,
           resolution=64, params=CostParams(), shrink=0.02, margin_step=0.25, loosen=3, threads=8):
    """problem.limit_c must be set; its carrier times `envelope` bounds the search. Returns a dict with the best
    certified design (or None), every round's record and the FV solves spent (calibration included).

    thermal=True: min-area MILP with the proxy envelope J <= -margin. The margin is a closed loop on the FV J of
    each certification (margin += J: a miss tightens it by at least margin_step, slack loosens it); a certified design
    caps the next area at (1 - shrink) of it. When the MILP finds nothing (proved infeasible or out of time; the
    solver status is recorded), the margin is loosened by margin_step at most `loosen` times in a row before the
    search stops. thermal=False (ablation): min-wire MILP
    under an area cap, bisected on the cap between the largest failed and the smallest certified area."""
    if problem.limit_c is None:
        raise ValueError('cosize needs absolute per-die limits (Problem.limit_c)')
    w_max, h_max = (s/1000*envelope for s in problem.carrier_um)
    envelope_problem = replace(problem, carrier_um=(w_max*1000, h_max*1000))
    levels = width_levels(problem, w_max)
    solves, model = 0, None
    if thermal:
        model = ThermalProxy.calibrate(problem, gap_um, resolution)
        solves += model.solves
    margin, wire_mm = 0.0, length_m*1000
    offset = None
    if thermal:
        # The axial envelope is biased high by a near-constant offset (docs/proxy-space-plan.md, 2026-11-17), so
        # J <= 0 in it would be needlessly strict: the margin starts at minus the offset measured by one FV solve on
        # the min-wire layout of the original carrier, and the closed loop corrects it from there.
        raw = milp_relations(problem, gap_um, milp_s)
        start = None if raw is None else legalize_relations(problem, raw, gap_um)
        if start is not None:
            (layout0, peaks0), = slp_chain((problem, start, gap_um, resolution, length_m, 0, 'length'))
            solves += 1
            offset = model.envelope_value(problem, layout0, gap_um) - float(peaks0.max())
            margin = -offset
    area_cap = None if thermal else w_max*h_max
    low = 0.0                                   # blind bisection: largest failed area
    loosened = 0
    cuts = []                                   # pin-length cuts, valid for every carrier
    best, history = None, []
    for r in range(rounds):
        if solves + steps + 1 > fv_budget:
            history.append(dict(round=r, stop='fv budget'))
            break
        found, statuses = sized_milp(problem, envelope_problem, levels, h_max, gap_um, milp_s, params, area_cap, wire_mm,
                           (model, -margin) if thermal else None, threads, cuts)
        if not found:
            history.append(dict(round=r, stop='milp found nothing', solver=statuses, margin_k=margin,
                                area_cap_mm2=area_cap))
            if thermal and loosened < loosen:
                loosened += 1
                margin -= margin_step
                continue
            if thermal or best is None:
                break
            low, area_cap = area_cap, (area_cap + best['width_mm']*best['height_mm'])/2
            continue
        cost, w, h, k, layout = min(found, key=lambda f: f[0])
        sized = replace(problem, carrier_um=(w*1000, h*1000))
        legal = legalize_relations(sized, layout, gap_um)
        record = dict(round=r, width_mm=w, height_mm=h, fields_allowed=k, cost_usd=cost, margin_k=margin, solver=statuses,
                      area_cap_mm2=area_cap, wire_budget_mm=wire_mm,
                      legal=legal is not None and is_legal(sized, legal, gap_um))
        ok, j_seen, l_seen = None, None, None
        if record['legal']:
            if thermal:
                record['envelope_j_k'] = model.envelope_value(sized, legal, gap_um)
            ok, (j_seen, l_seen), used = certify(sized, legal, gap_um, length_m, steps, resolution)
            solves += used
            record.update(fv_solves=used, best_j_k=j_seen, best_length_m=l_seen)
        record['certified'] = ok is not None
        history.append(record)
        if ok is not None and (best is None or cost < best['cost_usd']):
            c = interposer_cost(w, h, params)
            best = dict(width_mm=w, height_mm=h, cost_usd=cost, option=c['option'], fields=c['fields'], j_k=ok[1],
                        length_m=ok[2], centre_um=ok[0].centre_um.tolist(), rotation_deg=ok[0].rotation_deg.tolist(),
                        round=r)
        if thermal:
            if ok is not None:
                area_cap, loosened = w*h*(1 - shrink), 0
                margin += ok[1]                           # FV slack (J <= 0) loosens the margin
            elif j_seen is not None and j_seen <= 0:      # cool enough but over the exact wire budget
                cuts.append(legal)
            else:
                margin += max(j_seen or 0.0, margin_step)
        else:
            if ok is not None:
                area_cap = (low + w*h)/2 if low > 0 else w*h*(1 - 4*shrink)
            elif j_seen is not None and j_seen <= 0:      # only the exact wire budget failed: cut, same cap
                cuts.append(legal)
            else:
                low = w*h
                if best is None:
                    break                               # even the envelope fails: nothing to bisect
                area_cap = (low + best['width_mm']*best['height_mm'])/2
            if best is not None and best['width_mm']*best['height_mm'] - low < shrink*best['width_mm']*best['height_mm']:
                history.append(dict(round=r, stop='bisection converged'))
                break
    return dict(best=best, history=history, fv_solves=solves, calibration_solves=0 if model is None else model.solves,
                envelope_offset_k=offset, wire_cuts=len(cuts), thermal=thermal)
