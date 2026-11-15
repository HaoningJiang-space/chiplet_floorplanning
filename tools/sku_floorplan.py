"""One package, several products: does the full-product layout hold up for depopulated SKUs?
(plan: docs/sku-floorplan-plan.md)

Group = the most numerous compute kind with at least MIN_GROUP dies (k of them). Each tier enables m of
them at a per-die power from the EPYC 9004 data sheet ratios; the rest of the package stays nominal.
Per front layout the power-layer response of every group die and of the rest is solved once, and every
C(k, m) enable set is scored by superposition: designed population takes the coolest set, harvested the hottest.
"""
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
import json

import numpy as np

from chiplet_floorplanning.placement.thermal import AMBIENT_C, power_layer_responses
import frozen_front
from workload_leverage import is_compute, kind

MIN_GROUP = 4
# (name, enabled share, group power share): 9654 12 CCD 360 W; 9554/9474F 8 CCD 360 W; 9334 4 CCD 210 W (inferred).
TIERS = (('full', 1.0, 1.0), ('two_thirds', 2/3, 1.0), ('one_third', 1/3, 210/360))
IO_SHARE = 0.25                  # sensitivity: I/O takes this share of the full TDP, which does not scale
CAP_FACTOR, MEANINGFUL_K, RESOLUTION_K = 1.25, 1.0, 0.3


def group(names, power):
    """Indices of the most numerous compute kind (ties: higher total power), or None if fewer than MIN_GROUP."""
    kinds = [kind(n) for n, c in zip(names, is_compute(names)) if c]
    if not kinds:
        return None
    best = max(set(kinds), key=lambda x: (kinds.count(x),
                                          sum(p for n, p in zip(names, power) if kind(n) == x)))
    if kinds.count(best) < MIN_GROUP:
        return None
    return np.array([i for i, n in enumerate(names) if kind(n) == best])


def tiers(k, io_share=0.0):
    """(name, enabled count m, per-enabled-die power factor) per tier."""
    out = []
    for name, share, power in TIERS:
        m = k if share == 1 else max(1, round(share*k))
        power = (power - io_share)/(1 - io_share)
        out.append((name, m, power*k/m))
    return out


def tier_peaks(fixed, unit, m, factor):
    """Coolest and hottest power-layer peak (degC) over all enable sets of size m."""
    peaks = [np.nanmax(fixed + factor*unit[list(s)].sum(0)) for s in combinations(range(len(unit)), m)]
    return min(peaks) + AMBIENT_C, max(peaks) + AMBIENT_C


def layout_peaks(job):
    problem, layout, gap_um, resolution, members = job
    rest = problem.power_w.copy()
    rest[members] = 0
    columns = [np.where(np.arange(len(rest)) == i, problem.power_w, 0.) for i in members] + [rest]
    fields = power_layer_responses(problem, layout, gap_um, columns, resolution)
    unit, fixed = fields[:-1].reshape(len(members), -1), fields[-1].ravel()
    out = {}
    for io, label in ((0.0, ''), (IO_SHARE, 'io/')):
        for name, m, factor in tiers(len(members), io):
            if name == 'full' and io:
                continue
            out[label + name] = tier_peaks(fixed, unit, m, factor)
    return out


def choose(length, full, objective):
    within = np.flatnonzero(length <= CAP_FACTOR*length.min() + 1e-12)
    n = int(within[np.argmin(full[within])])
    s = int(within[np.argmin(objective[within])])
    return dict(nominal_best=n, sku_best=s, regret_k=float(objective[n] - objective[s]),
                reverse_cost_k=float(full[s] - full[n]), objective_at_nominal_best_c=float(objective[n]))


def objectives(peaks, labels):
    """J_designed (max over tiers of the coolest set) and J_harvested (max of the hottest), and the binding tier."""
    designed = np.array([[p[t][0] for t in labels] for p in peaks])
    harvested = np.array([[p[t][1] for t in labels] for p in peaks])
    return designed.max(1), harvested.max(1), [labels[i] for i in designed.argmax(1)], \
        [labels[i] for i in harvested.argmax(1)]


def verdict(regrets):
    hit = sum(r >= MEANINGFUL_K for r in regrets)
    return 'worthwhile' if hit >= 3 else 'degenerate' if all(r < RESOLUTION_K for r in regrets) else 'uncertain'


def analyse(case_path, summary_path, layouts_path, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem = front.problem
    members = group(problem.names, problem.power_w)
    if members is None:
        return None
    jobs = [(problem, l, front.gap_um, front.resolution, members) for l in front.layouts]
    with ProcessPoolExecutor(workers) as pool:
        peaks = list(pool.map(layout_peaks, jobs))
    full = np.array([p['full'][0] for p in peaks])
    if np.abs(full - front.peak_c).max() > 1e-6:
        raise SystemExit(f'{front.case}: superposed full-tier peaks differ from the frozen front')
    out = dict(case=front.case, group=problem.names[members[0]].rsplit('_', 1)[0], k=len(members),
               tiers=tiers(len(members)), io_tiers=tiers(len(members), IO_SHARE), front_index=front.index,
               length_m=front.length_m.tolist(), peaks_c=[{t: list(v) for t, v in p.items()} for p in peaks])
    for label, names in (('', [t[0] for t in TIERS]), ('io', ['full', 'io/two_thirds', 'io/one_third'])):
        designed, harvested, bind_d, bind_h = objectives(peaks, names)
        key = label + '_' if label else ''
        out[key + 'designed'] = dict(choose(front.length_m, full, designed), binding=bind_d)
        out[key + 'harvested'] = dict(choose(front.length_m, full, harvested), binding=bind_h)
    return out


def main():
    args = frozen_front.arguments(__doc__)
    cases = []
    for n in args.cases:
        r = analyse(*frozen_front.paths(args, n), args.workers)
        if r is None:
            print(f'Case{n}: no group of {MIN_GROUP}+ identical compute dies', flush=True)
            continue
        cases.append(r)
        print(r['case'], r['group'], r['k'], {m: round(r[m]['regret_k'], 2) for m in
                                              ('designed', 'harvested', 'io_designed', 'io_harvested')}, flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/sku-floorplan-plan.md', tiers=TIERS, io_share=IO_SHARE,
        cap_factor=CAP_FACTOR, meaningful_k=MEANINGFUL_K, resolution_k=RESOLUTION_K,
        verdict=verdict([c['designed']['regret_k'] for c in cases]),
        harvested_verdict=verdict([c['harvested']['regret_k'] for c in cases]), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
