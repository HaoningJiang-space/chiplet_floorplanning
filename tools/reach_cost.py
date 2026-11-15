"""Thermal cost of die-to-die link reach (plan: docs/reach-cost-plan.md).

A link joins every chiplet pair that shares ATPlace nets; its PHYs sit on the facing die edges, so its length is
the Manhattan gap between the two die rectangles. A packaging tier is usable only if every link fits its reach.
Per reach R: epsilon search for the coolest layout with max link gap <= R, from one shared start set and budget,
against the same search with no reach limit and the frozen front (which never saw the reach).
"""
import json
import time

import numpy as np

from chiplet_floorplanning.placement import Evaluator, boxes, sample_legal
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent
import frozen_front

# Silicon interposer / bridge (UCIe advanced 2 mm; PlaceIT table I 2-4 mm) and organic substrate (UCIe standard 25 mm).
REACHES_MM = (2.0, 4.0, 25.0)
UNLIMITED_MM = 1e9
SEED, FV_SOLVES, BATCH, STARTS = 2026111401, 1000, 48, 48


def link_pairs(problem):
    """(pairs, lanes): chiplet index pairs that share nets and their net counts."""
    pairs, lanes = np.unique(np.sort(problem.pin_chip, 1), axis=0, return_counts=True)
    return pairs, lanes


def link_gaps_mm(problem, layout, pairs):
    b = boxes(problem, layout)/1000
    x0, y0, x1, y1 = b[pairs[:, 0]].T
    u0, v0, u1, v1 = b[pairs[:, 1]].T
    return np.maximum(0, np.maximum(u0 - x1, x0 - u1)) + np.maximum(0, np.maximum(v0 - y1, y0 - v1))


def search(problem, initial, reach_mm, gap_um, resolution, workers, pairs):
    longest = lambda layout: link_gaps_mm(problem, layout, pairs).max()
    with Evaluator(problem, gap_um, resolution, workers, interconnect=longest) as evaluator:
        run = Run(evaluator, FV_SOLVES)
        METHODS['epsilon'](run, initial, np.random.default_rng([SEED, 20]), batch=BATCH, length_caps_m=[reach_mm])
        gap, peak, _ = run.arrays()
        solves = evaluator.solves
    ok = np.flatnonzero(gap <= reach_mm + 1e-9)
    if not ok.size:
        return dict(feasible=False, solves=solves, stop=run.stop_reason)
    best = int(ok[np.argmin(peak[ok])])
    layout = run.layouts[best]
    return dict(feasible=True, peak_c=float(peak[best]), longest_gap_mm=float(gap[best]), feasible_layouts=int(ok.size),
                solves=solves, stop=run.stop_reason, centre_um=layout.centre_um.tolist(),
                rotation_deg=layout.rotation_deg.tolist())


def analyse(case_path, summary_path, layouts_path, workers):
    front = frozen_front.load(case_path, summary_path, layouts_path)
    problem, gap, res = front.problem, front.gap_um, front.resolution
    pairs, lanes = link_pairs(problem)
    front_gap = np.array([link_gaps_mm(problem, l, pairs).max() for l in front.layouts])
    rng = np.random.default_rng(SEED)
    initial = [sample_legal(problem, gap, rng) for _ in range(STARTS)]
    initial += [length_descent(problem, sample_legal(problem, gap, rng), rng, gap) for _ in range(STARTS)]
    started = time.perf_counter()
    out = dict(case=front.case, links=len(pairs), lanes=lanes.tolist(), pairs=pairs.tolist(),
               front=dict(coolest_c=float(front.peak_c.min()), by_reach={}), search={})
    for r in REACHES_MM:
        ok = front_gap <= r + 1e-9
        out['front']['by_reach'][str(r)] = float(front.peak_c[ok].min()) if ok.any() else None
    for r in (UNLIMITED_MM,) + REACHES_MM:
        out['search'][str(r)] = search(problem, initial, r, gap, res, workers, pairs)
    base = min(out['search'][str(UNLIMITED_MM)]['peak_c'], out['front']['coolest_c'])
    out['reference_coolest_c'] = base
    out['reach_cost_k'] = {str(r): (out['search'][str(r)]['peak_c'] - base if out['search'][str(r)]['feasible'] else None)
                           for r in REACHES_MM}
    print(front.case, {r: c and round(c, 2) for r, c in out['reach_cost_k'].items()},
          f'{time.perf_counter() - started:.0f}s', flush=True)
    return out


def main():
    args = frozen_front.arguments(__doc__)
    cases = [analyse(*frozen_front.paths(args, n), args.workers) for n in args.cases]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/reach-cost-plan.md', reaches_mm=REACHES_MM, seed=SEED,
        fv_solves=FV_SOLVES, cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
