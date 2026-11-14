"""Paired search-method comparison under one exact-FV budget.

  --freeze   derive caps from a reference front and write a plan (before any run)
  --execute  run every method and seed in the plan; shared start set per seed
  --report   gaps to the best known layout per cap (union of all runs and the reference)

Caps (frozen from the reference front summary):
  length caps: shortest front length reaching within {2, 1, 0.5} K of the coolest front peak;
  peak caps:   coolest front peak with length <= {1.1, 1.25, 1.5} x the shortest front length.
Each metric is one real layout's (length, peak); never mixed across layouts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.placement import Evaluator, Problem, coolest_within, sample_legal, shortest_within
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent

PEAK_MARGINS_K = (2.0, 1.0, 0.5)
LENGTH_FACTORS = (1.1, 1.25, 1.5)
CHECKPOINTS = (0.25, 0.5, 1.0)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(args):
    front = json.loads(args.reference.read_text())['front']
    length = np.array([p['length_m'] for p in front])
    peak = np.array([p['peak_c'] for p in front])
    plan = dict(
        protocol='method-comparison-v1', case_path=str(args.case), case_sha256=sha256(args.case),
        reference_summary=str(args.reference), reference_sha256=sha256(args.reference),
        methods=args.methods, seeds=args.seeds, fv_solves=args.fv_solves, batch=args.batch,
        random_starts=args.random_starts, descent_starts=args.descent_starts, gap_um=args.gap_um,
        resolution=args.resolution, budget_unit='distinct FV solves, shared start set included',
        length_caps_m=[float(length[peak <= peak.min() + m].min()) for m in PEAK_MARGINS_K],
        peak_caps_c=[float(peak[length <= f*length.min()].min()) for f in LENGTH_FACTORS],
        cap_rules=dict(length=f'shortest front L with T <= Tmin + {PEAK_MARGINS_K} K',
                       peak=f'coolest front T with L <= {LENGTH_FACTORS} x Lmin'),
        code=source_revision())
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    if args.plan.exists():
        raise SystemExit(f'plan exists; frozen plans are not overwritten: {args.plan}')
    args.plan.write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(plan, indent=2))


def metrics(plan, length, peak, cost):
    out = {}
    for fraction in CHECKPOINTS:
        upto = cost <= fraction*plan['fv_solves']
        l, p = length[upto], peak[upto]
        pick = lambda i: None if i is None else dict(length_m=float(l[i]), peak_c=float(p[i]))
        out[str(fraction)] = dict(
            coolest_within_length_cap={str(c): pick(coolest_within(l, p, c)) for c in plan['length_caps_m']},
            shortest_within_peak_cap={str(c): pick(shortest_within(l, p, c)) for c in plan['peak_caps_c']})
    return out


def execute(args):
    plan = json.loads(args.plan.read_text())
    if sha256(plan['case_path']) != plan['case_sha256']:
        raise SystemExit('case input changed since freezing')
    problem = Problem.from_imported(json.loads(Path(plan['case_path']).read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    source = source_revision()
    for seed in plan['seeds']:
        rng = np.random.default_rng(seed)
        initial = [sample_legal(problem, plan['gap_um'], rng) for _ in range(plan['random_starts'])]
        initial += [length_descent(problem, sample_legal(problem, plan['gap_um'], rng), rng, plan['gap_um'])
                    for _ in range(plan['descent_starts'])]
        for name in plan['methods']:
            started = time.perf_counter()
            with Evaluator(problem, plan['gap_um'], plan['resolution'], args.workers) as evaluator:
                run = Run(evaluator, plan['fv_solves'])
                METHODS[name](run, initial, np.random.default_rng([seed, len(name)] + [ord(c) for c in name]),
                              batch=plan['batch'], length_caps_m=plan['length_caps_m'])
            length, peak, cost = run.arrays()
            record = dict(method=name, seed=seed, fv_solves=evaluator.solves, layouts=len(run.layouts),
                          wall_seconds=time.perf_counter() - started, workers=args.workers,
                          code_commit=source['commit'], code_dirty=source['dirty'],
                          plan_sha256=sha256(args.plan), metrics=metrics(plan, length, peak, cost))
            stem = args.output/f'{name}-seed{seed}'
            stem.with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n')
            np.savez_compressed(stem.with_suffix('.npz'), centre_um=np.array([l.centre_um for l in run.layouts]),
                                rotation_deg=np.array([l.rotation_deg for l in run.layouts]),
                                length_m=length, peak_c=peak, cost=cost)
            final = record['metrics']['1.0']
            print(name, seed, f"{record['wall_seconds']:.0f}s",
                  {k: v and round(v['peak_c'], 4) for k, v in final['coolest_within_length_cap'].items()},
                  {k: v and round(v['length_m'], 3) for k, v in final['shortest_within_peak_cap'].items()}, flush=True)


def report(args):
    plan = json.loads(args.plan.read_text())
    records = [json.loads(p.read_text()) for p in sorted(args.output.glob('*-seed*.json'))]
    ref = json.loads(Path(plan['reference_summary']).read_text())['front']
    ref_l, ref_p = np.array([p['length_m'] for p in ref]), np.array([p['peak_c'] for p in ref])
    runs = {(r['method'], r['seed']): np.load(args.output/f"{r['method']}-seed{r['seed']}.npz") for r in records}
    all_l = np.concatenate([ref_l] + [d['length_m'] for d in runs.values()])
    all_p = np.concatenate([ref_p] + [d['peak_c'] for d in runs.values()])
    best_t = {str(c): float(all_p[coolest_within(all_l, all_p, c)]) for c in plan['length_caps_m']}
    best_l = {str(c): float(all_l[shortest_within(all_l, all_p, c)]) for c in plan['peak_caps_c']}
    table = {}
    for method in plan['methods']:
        rows = [r for r in records if r['method'] == method]
        out = {}
        for fraction in map(str, CHECKPOINTS):
            gap_t = {c: [r['metrics'][fraction]['coolest_within_length_cap'][c]['peak_c'] - best_t[c]
                         if r['metrics'][fraction]['coolest_within_length_cap'][c] else None for r in rows]
                     for c in best_t}
            gap_l = {c: [(r['metrics'][fraction]['shortest_within_peak_cap'][c]['length_m'] - best_l[c])/best_l[c]
                         if r['metrics'][fraction]['shortest_within_peak_cap'][c] else None for r in rows]
                     for c in best_l}
            out[fraction] = dict(peak_gap_k=gap_t, length_gap_fraction=gap_l)
        table[method] = out
    summary = dict(best_known_peak_c=best_t, best_known_length_m=best_l, seeds=plan['seeds'],
                   note='gaps are per seed (paired by shared start set); None = cap not reached', methods=table)
    (args.output/'report.json').write_text(json.dumps(summary, indent=2) + '\n')
    for method, out in table.items():
        final = out['1.0']
        med = lambda xs: None if any(x is None for x in xs) else round(float(np.median(xs)), 4)
        print(method, 'peak gap K', {c: med(v) for c, v in final['peak_gap_k'].items()},
              'length gap', {c: med(v) for c, v in final['length_gap_fraction'].items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--report', action='store_true')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--case', type=Path)
    parser.add_argument('--reference', type=Path, help='reference front summary.json')
    parser.add_argument('--methods', nargs='+', default=list(METHODS))
    parser.add_argument('--seeds', type=int, nargs='+', default=[2026111401])
    parser.add_argument('--fv-solves', type=int, default=2000)
    parser.add_argument('--batch', type=int, default=48)
    parser.add_argument('--random-starts', type=int, default=48)
    parser.add_argument('--descent-starts', type=int, default=48)
    parser.add_argument('--gap-um', type=float, default=1000)
    parser.add_argument('--resolution', type=int, default=64)
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.freeze:
        if not (args.case and args.reference):
            parser.error('--freeze needs --case and --reference')
        freeze(args)
    elif not args.output:
        parser.error('--execute/--report need --output')
    elif args.execute:
        execute(args)
    else:
        report(args)


if __name__ == '__main__':
    main()
