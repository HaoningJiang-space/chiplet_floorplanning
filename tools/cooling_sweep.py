"""How much placement can cool a case as cooling gets stronger (plan: docs/cooling-sweep-plan.md).

Every front layout of each case is re-solved with the FV model at several sink-top h values; per h the shortest
layout's peak, the gap to the coolest front layout and that gap within 1.25x the shortest length are reported.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um, solve, thermal_case_data

H_W_M2K = (500.0, 1500.0, 5000.0, 15000.0, 50000.0)
RESOLUTION = 64
AMBIENT_C = 45.0


def peak_c(args):
    problem, layout, gap_um = args
    return solve(thermal_case_data(problem, layout, gap_um, RESOLUTION))[0]['peak_power_layer_c']


def leverage(length, peak):
    """Shortest layout's peak, its gap to the coolest layout, the relative gap and the gap within 1.25x length."""
    s = int(np.argmin(length))
    near = length <= 1.25*length[s]
    gap = float(peak[s] - peak.min())
    return dict(shortest_peak_c=float(peak[s]), gap_k=gap, relative=gap/float(peak[s] - AMBIENT_C),
                gap_125_k=float(peak[s] - peak[near].min()))


def verdict(rows):
    shrank = sum(r['5e+04']['gap_k'] < 0.5*r['1.5e+03']['gap_k'] for r in rows.values())
    grew = sum(r['5e+04']['gap_k'] >= r['1.5e+03']['gap_k'] for r in rows.values())
    return 'confirmed' if shrank >= 10 else 'rejected' if grew >= 4 else 'partial'


def load(case_path, run_dir):
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    summary = json.loads((run_dir/'summary.json').read_text())
    z = np.load(run_dir/'layouts.npz')
    layouts = [Layout(z['centre_um'][p['index']], z['rotation_deg'][p['index']]) for p in summary['front']]
    return problem, layouts, summary['gap_um']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', nargs=3, action='append', metavar=('NAME', 'CASE_JSON', 'RUN_DIR'), required=True)
    p.add_argument('--workers', type=int, default=24)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    rows = {}
    with ProcessPoolExecutor(args.workers) as pool:
        for name, case, run in args.case:
            problem, layouts, gap = load(case, Path(run))
            length = np.array([pin_manhattan_um(problem, l).sum()/1e6 for l in layouts])
            rows[name] = {}
            for h in H_W_M2K:
                cooled = replace(problem, top_h_w_m2k=h)
                peak = np.array(list(pool.map(peak_c, [(cooled, l, gap) for l in layouts])))
                rows[name][f'{h:.2g}'] = leverage(length, peak)
            print(name, len(layouts), {h: (round(r['shortest_peak_c'], 1), round(r['gap_k'], 2), round(r['gap_125_k'], 2))
                                       for h, r in rows[name].items()}, flush=True)
    out = dict(plan='docs/cooling-sweep-plan.md', h_w_m2k=H_W_M2K, verdict=verdict(rows), cases=rows)
    args.output.write_text(json.dumps(out, indent=1) + '\n')
    print(out['verdict'])


if __name__ == '__main__':
    main()
