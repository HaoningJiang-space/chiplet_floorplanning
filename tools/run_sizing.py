"""Joint interposer sizing and placement vs size-then-place (plan: docs/sizing-placement-plan.md).

For one case and area budget A_b: the carrier-sized relation MILP ranks shapes by wire length (K shapes, each next
one excluding widths within +-10% of those already taken); each shape gets the full box its width level allows,
W_l x min(H_max, A_b / W_l), and relation_space with an equal share of the FV budget, seeded with the legalised MILP
layout. The size-then-place baseline keeps the original aspect ratio at area A_b and gets the whole budget.
Every evaluated layout is recorded with its carrier cost, so fronts over (cost, peak, length) can be formed later.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.placement import Evaluator, Problem, is_legal, sample_legal
from chiplet_floorplanning.placement.cost import interposer_cost
from chiplet_floorplanning.placement.lp import legalize_relations, milp_relations
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent

FACTORS = (0.85, 0.92, 1.0, 1.1, 1.25, 1.5)
WIDTH_STEP_MM = 0.5
SHAPES = 3
EXCLUDE = 0.10
ASPECT = 3.0          # declared: interposer sides within 1:3 .. 3:1


def width_levels(problem, area_mm2):
    """Width levels (mm), 0.5 mm apart, with the aspect ratio within ASPECT and room for the widest die."""
    narrow = problem.size_um.min(axis=1).max()/1000
    low, high = max(narrow, math.sqrt(area_mm2/ASPECT)), min(area_mm2/narrow, math.sqrt(area_mm2*ASPECT))
    return np.arange(math.ceil(low/WIDTH_STEP_MM)*WIDTH_STEP_MM, high + 1e-9, WIDTH_STEP_MM)


def shapes(problem, gap_um, area_mm2, milp_s):
    """Up to SHAPES (width, height, milp layout) by wire length; heights take the whole allowed box."""
    levels = width_levels(problem, area_mm2)
    envelope = replace(problem, carrier_um=(levels.max()*1000, area_mm2/levels.min()*1000))
    taken, out = [], []
    for _ in range(SHAPES):
        excluded = [l for l, v in enumerate(levels) if any(abs(v - levels[t]) <= EXCLUDE*levels[t] for t in taken)]
        found = milp_relations(envelope, gap_um, milp_s, sizing=(levels, area_mm2, excluded))
        if found is None:
            break
        layout, _, level = found
        taken.append(level)
        out.append((float(levels[level]), float(min(envelope.carrier_um[1]/1000, area_mm2/levels[level])), layout))
    return out


def run_front(problem, gap_um, budget, seed, extra_starts, method_options):
    """relation_space on a fixed carrier; returns (per-layout rows, archive arrays). The thermal value is the
    peak in degC, or with Problem.limit_c the overshoot J in K; the archive keeps every layout and die value."""
    rng = np.random.default_rng(seed)
    starts = [s for s in extra_starts if s is not None and is_legal(problem, s, gap_um)]
    try:
        starts += [sample_legal(problem, gap_um, rng) for _ in range(24)]
        starts += [length_descent(problem, sample_legal(problem, gap_um, rng), rng, gap_um) for _ in range(24)]
    except RuntimeError:
        pass                                    # tight carrier: MILP seeds only (relation_space builds its own)
    with Evaluator(problem, gap_um, 64, method_options.pop('workers', 16)) as evaluator:
        run = Run(evaluator, budget)
        METHODS['relation_space'](run, starts, rng, batch=48, **method_options)
        length, thermal, _ = run.arrays()
        die, _ = run.local()
        solves = evaluator.solves
    archive = dict(centre_um=np.array([l.centre_um for l in run.layouts]),
                   rotation_deg=np.array([l.rotation_deg for l in run.layouts]), length_m=length, thermal=thermal,
                   die_thermal=die, carrier_um=np.array(problem.carrier_um), solves=solves)
    return [dict(length_m=float(l), thermal=float(t)) for l, t in zip(length, thermal)], archive


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--factors', type=float, nargs='+', default=list(FACTORS))
    p.add_argument('--fv-solves', type=int, default=1000)
    p.add_argument('--gap-um', type=float, default=0)
    p.add_argument('--milp-s', type=float, default=120)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    problem = Problem.from_imported(json.loads(args.case.read_text()))
    width0, height0 = (s/1000 for s in problem.carrier_um)
    identity = dict(case_path=str(args.case), case_sha256=hashlib.sha256(args.case.read_bytes()).hexdigest(),
                    code=source_revision(), limit_c=None if problem.limit_c is None else problem.limit_c.tolist(),
                    thermal_kind='peak_c' if problem.limit_c is None else 'overshoot_k', names=list(problem.names))
    for factor in args.factors:
        started = time.perf_counter()
        area = factor*width0*height0
        record = dict(case=problem.name, factor=factor, area_factor=factor, area_mm2=area, seed=args.seed,
                      fv_solves=args.fv_solves, plan='docs/sizing-placement-plan.md + docs/sizing-plan-revisions.md',
                      joint=[], baseline=None, **identity)
        tag = f'factor{factor:g}'.replace('.', 'p')

        def keep(name, archive):
            np.savez_compressed(args.output/f'{tag}_{name}.npz', **archive)
            return dict(archive=f'{tag}_{name}.npz', solves=int(archive['solves']))
        for k, (width, height, layout) in enumerate(shapes(problem, args.gap_um, area, args.milp_s)):
            sized = replace(problem, carrier_um=(width*1000, height*1000))
            seed_layout = legalize_relations(sized, layout, args.gap_um)
            entry = dict(width_mm=width, height_mm=height, cost=interposer_cost(width, height),
                         seeded=seed_layout is not None, rows=[], error=None)
            try:
                entry['rows'], archive = run_front(sized, args.gap_um, args.fv_solves//SHAPES, args.seed,
                                                   [seed_layout], dict(milp_s=args.milp_s, workers=args.workers))
                entry.update(keep(f'shape{k}', archive))
            except RuntimeError as error:
                entry['error'] = str(error)
            record['joint'].append(entry)
        scale = math.sqrt(factor)
        base = replace(problem, carrier_um=(problem.carrier_um[0]*scale, problem.carrier_um[1]*scale))
        record['baseline'] = dict(width_mm=width0*scale, height_mm=height0*scale,
                                  cost=interposer_cost(width0*scale, height0*scale), rows=[], error=None)
        try:
            record['baseline']['rows'], archive = run_front(base, args.gap_um, args.fv_solves, args.seed, [],
                                                            dict(milp_s=args.milp_s, workers=args.workers))
            record['baseline'].update(keep('baseline', archive))
        except RuntimeError as error:
            record['baseline']['error'] = str(error)
        record['wall_s'] = time.perf_counter() - started
        (args.output/f'{tag}.json').write_text(json.dumps(record, default=float) + '\n')
        best = lambda rows: (round(min(r['thermal'] for r in rows), 2), round(min(r['length_m'] for r in rows), 3)) if rows else None
        print(problem.name, factor, 'joint', [(round(j['width_mm'], 1), round(j['height_mm'], 1), best(j['rows']))
                                              for j in record['joint']],
              'baseline', best(record['baseline']['rows']), round(record['wall_s']), 's', flush=True)


if __name__ == '__main__':
    main()
