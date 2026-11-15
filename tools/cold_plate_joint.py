"""Separate versus joint layout-cooling design on a liquid cold plate (plan: docs/cold-plate-joint-plan.md).

Separate: optimise the layout for the air sink (frozen front plus an lp_epsilon run), keep the air
Pareto set, then put it on the cold plate. Joint: run lp_epsilon directly on the cold plate (each
layout scored with its best flow direction at FLOW_LPM), from the same start set and budget.
Per length cap c x Lmin: gain = coolest separate peak - coolest joint peak on the cold plate, and the
flow the joint layout needs to match the separate one (peak(Q) fitted as alpha + beta/Q), so the
pumping saving is 1 - (Q_joint/FLOW_LPM)**PUMP_EXPONENT.
"""
import json
import time

import numpy as np

from chiplet_floorplanning.placement import Evaluator, pareto_front, sample_legal, thermal_case_data
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent
from chiplet_floorplanning.placement.thermal import FLOW_DIRECTIONS, solve_cold_plate
import frozen_front

H_W_M2K, FLOW_LPM, FIT_FLOWS_LPM = 2e4, 1.0, (0.5, 1.0, 2.0)
PUMP_EXPONENT = 2.85                 # Milpower M3001 datasheet fit (docs/cold-plate-literature-calibration.md)
CAPS = (1.0, 1.1, 1.25, 1.5)
SEED, FV_SOLVES, BATCH, STARTS = 2026111401, 1000, 48, 48
MEANINGFUL_K, RESOLUTION_K = 1.0, 0.3
KG_S_PER_LPM = 0.997/60


def fit(peak):
    """Least-squares alpha + beta/Q over FIT_FLOWS_LPM for array (..., flows); returns alpha, beta, max error K."""
    x = np.c_[np.ones(len(FIT_FLOWS_LPM)), 1/np.array(FIT_FLOWS_LPM)]
    coef, *_ = np.linalg.lstsq(x, peak.reshape(-1, len(FIT_FLOWS_LPM)).T, rcond=None)
    error = np.abs(x @ coef - peak.reshape(-1, len(FIT_FLOWS_LPM)).T).max(axis=0)
    shape = peak.shape[:-1]
    return coef[0].reshape(shape), coef[1].reshape(shape), error.reshape(shape)


def needed_flow(alpha, beta, target):
    return np.where(target > alpha, beta/np.maximum(target - alpha, 1e-12), np.inf)


def flow_to_reach(problem, layout, gap_um, resolution, target_c):
    """Smallest flow (L/min, best direction) whose fitted peak meets target_c, and the fit error."""
    data = thermal_case_data(problem, layout, gap_um, resolution, cold_plate_h_w_m2k=H_W_M2K)
    peak = np.array([[solve_cold_plate(data, q*KG_S_PER_LPM, d)[0]['peak_power_layer_c'] for q in FIT_FLOWS_LPM]
                     for d in FLOW_DIRECTIONS])
    alpha, beta, error = fit(peak)
    return float(needed_flow(alpha, beta, target_c).min()), float(error.max())


def search(problem, initial, caps, gap_um, resolution, workers, cold_plate):
    with Evaluator(problem, gap_um, resolution, workers, cold_plate) as evaluator:
        run = Run(evaluator, FV_SOLVES)
        METHODS['lp_epsilon'](run, initial, np.random.default_rng([SEED, 10]), batch=BATCH, length_caps_m=caps)
        length, peak, _ = run.arrays()
    return run.layouts, length, peak


def compare(caps, sep_length, sep_peak, joint_length, joint_peak):
    """Coolest cold-plate peak within each cap for the separate and the joint candidate sets."""
    rows = {}
    for c, cap in caps.items():
        s = np.flatnonzero(sep_length <= cap + 1e-12)
        j = np.flatnonzero(joint_length <= cap + 1e-12)
        if not s.size or not j.size:
            rows[c] = None
            continue
        s, j = int(s[np.argmin(sep_peak[s])]), int(j[np.argmin(joint_peak[j])])
        rows[c] = dict(separate=s, joint=j, gain_k=float(sep_peak[s] - joint_peak[j]),
                       separate_peak_c=float(sep_peak[s]), joint_peak_c=float(joint_peak[j]))
    return rows


def verdict(cases):
    gains = [[r['gain_k'] for r in c.values() if r is not None] for c in cases]
    hit = sum(any(g >= MEANINGFUL_K for g in case) for case in gains)
    return 'worthwhile' if hit >= 3 else 'degenerate' if all(g < RESOLUTION_K for case in gains for g in case) \
        else 'uncertain'


def analyse(case_path, summary_path, layouts_path, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    caps = {str(c): c*front.length_m.min() for c in CAPS}
    rng = np.random.default_rng(SEED)
    initial = [sample_legal(problem, gap, rng) for _ in range(STARTS)]
    initial += [length_descent(problem, sample_legal(problem, gap, rng), rng, gap) for _ in range(STARTS)]
    plate = (H_W_M2K, FLOW_LPM*KG_S_PER_LPM)
    started = time.perf_counter()

    air_layouts, air_length, air_peak = search(problem, initial, list(caps.values()), gap, res, workers, None)
    pool = front.layouts + air_layouts
    pool_length, pool_peak = np.r_[front.length_m, air_length], np.r_[front.peak_c, air_peak]
    keep = pareto_front(pool_length, pool_peak)            # what a separate designer would hand over
    separate = [pool[i] for i in keep]
    with Evaluator(problem, gap, res, workers, plate) as evaluator:
        sep_peak = evaluator.peaks_c(separate)
    sep_length = pool_length[keep]

    joint_layouts, joint_length, joint_peak = search(problem, initial, list(caps.values()), gap, res, workers, plate)
    # The joint designer also knows the separate candidates, so the gain is never negative by construction.
    all_layouts = separate + joint_layouts
    all_length, all_peak = np.r_[sep_length, joint_length], np.r_[sep_peak, joint_peak]
    rows = compare(caps, sep_length, sep_peak, all_length, all_peak)
    for c, r in rows.items():
        if r is None:
            continue
        joint = all_layouts[r['joint']]
        q, err = flow_to_reach(problem, joint, gap, res, r['separate_peak_c'])
        r.update(joint_from='separate' if r['joint'] < len(separate) else 'joint_search',
                 separate_length_m=float(sep_length[r['separate']]), joint_length_m=float(all_length[r['joint']]),
                 joint_flow_lpm=q, fit_error_k=err, pumping_saving=float(1 - min(q/FLOW_LPM, 1e6)**PUMP_EXPONENT),
                 joint_centre_um=joint.centre_um.tolist(), joint_rotation_deg=joint.rotation_deg.tolist())
    print(front.case, {c: r and (round(r['gain_k'], 2), round(r['pumping_saving'], 3), r['joint_from'])
                       for c, r in rows.items()}, f'{time.perf_counter() - started:.0f}s', flush=True)
    return dict(case=front.case, caps_m=caps, separate_layouts=len(separate), joint_layouts=len(joint_layouts),
                rows=rows)


def main():
    args = frozen_front.arguments(__doc__)
    cases = [analyse(*frozen_front.paths(args, n), args.workers) for n in args.cases]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/cold-plate-joint-plan.md', h_w_m2k=H_W_M2K, flow_lpm=FLOW_LPM,
        fit_flows_lpm=FIT_FLOWS_LPM, pump_exponent=PUMP_EXPONENT, caps=CAPS, seed=SEED, fv_solves=FV_SOLVES,
        verdict=verdict([c['rows'] for c in cases]), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
