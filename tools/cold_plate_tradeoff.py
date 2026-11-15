"""Layout x coolant flow x flow direction on a liquid cold plate (plan: docs/cold-plate-tradeoff-plan.md).

Every front layout is solved for each cold-plate h, flow direction and flow rate. Peak(Q) per (layout,
direction) is fitted as alpha + beta/Q (the coolant rise scales with 1/Q); the flow needed to meet a
target is beta/(target - alpha). Pumping power ~ Q**3 (declared). Reported per case and h:
  direction regret: best peak of the direction-blind choice (coolest under fixed coolant within 1.25 Lmin,
                    then its best direction) minus the best (layout, direction) within the same cap;
  trade-off:        flow needed to reach the target with layouts within {1.0, 1.1, 1.25, 1.5} x Lmin.
"""
from concurrent.futures import ProcessPoolExecutor
import itertools
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data
from chiplet_floorplanning.placement.thermal import solve_cold_plate
import frozen_front

H_W_M2K = (1e4, 2e4, 4e4)          # effective microchannel coefficient on the base; 2e4 is primary
FLOWS_LPM = (0.5, 1., 2.)
DIRECTIONS = ('+x', '-x', '+y', '-y')
CAPS = (1.0, 1.1, 1.25, 1.5)
TARGET_FLOW_LPM = 1.               # target = direction-blind best peak at this flow
PUMP_EXPONENT = 3.
MEANINGFUL_K, RESOLUTION_K, PUMP_RATIO = 1.0, 0.3, 2.0
KG_S_PER_LPM = 0.997/60


def peaks(job):
    case_path, centre, rotation, gap_um, resolution, h = job
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    data = thermal_case_data(problem, Layout(centre, rotation), gap_um, resolution, cold_plate_h_w_m2k=h)
    fixed = solve_peak(data)['peak_power_layer_c']
    return fixed, [[solve_cold_plate(data, q*KG_S_PER_LPM, d)['peak_power_layer_c'] for q in FLOWS_LPM]
                   for d in DIRECTIONS]


def fit(peak):
    """Least-squares alpha + beta/Q over FLOWS_LPM for array (..., flows); returns alpha, beta, max error K."""
    x = np.c_[np.ones(len(FLOWS_LPM)), 1/np.array(FLOWS_LPM)]
    coef, *_ = np.linalg.lstsq(x, peak.reshape(-1, len(FLOWS_LPM)).T, rcond=None)
    error = np.abs(x @ coef - peak.reshape(-1, len(FLOWS_LPM)).T).max(axis=0)
    shape = peak.shape[:-1]
    return coef[0].reshape(shape), coef[1].reshape(shape), error.reshape(shape)


def needed_flow(alpha, beta, target):
    return np.where(target > alpha, beta/np.maximum(target - alpha, 1e-12), np.inf)


def summarise(length, fixed, plate):
    """length (layouts,), fixed (layouts,), plate (layouts, directions, flows)."""
    length = np.asarray(length)
    within = length <= 1.25*length.min()
    blind = int(np.flatnonzero(within)[np.argmin(fixed[within])])
    out = dict(blind_layout=blind, regret_k={}, best={})
    for f, q in enumerate(FLOWS_LPM):
        aware = plate[within][:, :, f].min()
        out['regret_k'][str(q)] = float(plate[blind, :, f].min() - aware)
    alpha, beta, error = fit(plate)
    target = float(plate[blind, :, FLOWS_LPM.index(TARGET_FLOW_LPM)].min())
    flow = needed_flow(alpha, beta, target)                # (layouts, directions)
    caps = {}
    for c in CAPS:
        ok = np.flatnonzero(length <= c*length.min() + 1e-12)
        k, d = np.unravel_index(np.argmin(flow[ok]), flow[ok].shape)
        caps[str(c)] = dict(layout=int(ok[k]), direction=DIRECTIONS[d], flow_lpm=float(flow[ok][k, d]),
                            length_m=float(length[ok[k]]))
    shortest = caps['1.0']['flow_lpm']
    out.update(target_c=target, fit_error_max_k=float(error.max()), caps=caps,
               blind_flow_lpm=float(flow[blind].min()),
               pump_ratio_short_vs_125=float((shortest/caps['1.25']['flow_lpm'])**PUMP_EXPONENT)
               if np.isfinite(shortest) else None)
    return out


def verdict(cases):
    regret = [c['regret_k'][str(TARGET_FLOW_LPM)] for c in cases]
    coupling = ('worthwhile' if sum(r >= MEANINGFUL_K for r in regret) >= 3 else
                'degenerate' if all(r < RESOLUTION_K for r in regret) else 'uncertain')
    ratio = [c['pump_ratio_short_vs_125'] for c in cases]
    tradeoff = sum(r is None or r >= PUMP_RATIO for r in ratio) >= 3  # None: shortest cannot reach the target
    return dict(direction_coupling=coupling, length_pumping_tradeoff=bool(tradeoff))


def analyse(case_path, summary_path, layouts_path, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    length = front.length_m
    jobs = [(str(case_path), l.centre_um, l.rotation_deg, front.gap_um, front.resolution, h)
            for h, l in itertools.product(H_W_M2K, front.layouts)]
    with ProcessPoolExecutor(workers) as pool:
        solved = list(pool.map(peaks, jobs, chunksize=2))
    out = dict(case=front.case, front_index=front.index, length_m=length.tolist(), by_h={})
    for j, h in enumerate(H_W_M2K):
        rows = solved[j*len(front.layouts):(j + 1)*len(front.layouts)]
        fixed, plate = np.array([r[0] for r in rows]), np.array([r[1] for r in rows])
        out['by_h'][str(h)] = dict(summarise(length, fixed, plate), fixed_c=fixed.tolist(), plate_c=plate.tolist())
    return out


def main():
    args = frozen_front.arguments(__doc__)
    cases = []
    for n in args.cases:
        r = analyse(*frozen_front.paths(args, n), args.workers)
        cases.append(r)
        print(r['case'], {h: (v['regret_k'], v['pump_ratio_short_vs_125'], round(v['fit_error_max_k'], 3))
                          for h, v in r['by_h'].items()}, flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/cold-plate-tradeoff-plan.md',
        h_w_m2k=H_W_M2K, flows_lpm=FLOWS_LPM,
        directions=DIRECTIONS, caps=CAPS, pump_exponent=PUMP_EXPONENT,
        verdict={h: verdict([c['by_h'][str(h)] for c in cases]) for h in map(str, H_W_M2K)}, cases=cases),
        indent=1) + '\n')


if __name__ == '__main__':
    main()
