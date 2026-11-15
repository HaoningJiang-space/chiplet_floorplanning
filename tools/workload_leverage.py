"""Does the best layout depend on the workload? (plan: docs/workload-leverage-plan.md)

Every front layout is re-solved under declared per-chiplet activity scenarios. Two families:
`budget` redistributes the freed power to compute dies left at full activity (at most BOOST x nominal,
the rest is dropped), so the package power stays at most the nominal total; `activity` only scales.
Per scenario: regret of the nominal-best layout = its peak minus the coolest front peak within
1.25 x Lmin under that scenario.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data

COMPUTE, MEMORY = ('CPU', 'GPU', 'Virtuvian'), ('HBM', 'DRAM')
IDLE, BOOST = 0.2, 1.5
CAP_FACTOR = 1.25
MEANINGFUL_K, RESOLUTION_K = 1.0, 0.3


def kind(name):
    return re.match(r'[A-Za-z]+\d*', name).group(0)


def is_compute(names):
    return np.array([kind(n).startswith(COMPUTE) for n in names])


def scenarios(names):
    """Activity multipliers per declared scenario; scenarios equal to nominal are left out."""
    k = [kind(n) for n in names]
    compute = is_compute(names)
    memory = np.array([x.startswith(MEMORY) for x in k])
    counts = {x: k.count(x) for x in k}
    index = np.array([int(n.rsplit('_', 1)[1]) for n in names])
    paired = compute & np.array([counts[x] >= 2 for x in k])
    raw = dict(memory_idle=np.where(memory, .3, 1.), compute_half=np.where(compute, .5, 1.),
               gpu_idle=np.where([x == 'GPU' for x in k], IDLE, 1.),
               cpu_idle=np.where([x.startswith('CPU') for x in k], IDLE, 1.),
               odd_idle=np.where(paired & (index % 2 == 1), IDLE, 1.),
               even_idle=np.where(paired & (index % 2 == 0), IDLE, 1.))
    # A scenario that idles every compute die, or changes nothing, is not a workload shift.
    return {s: m for s, m in raw.items() if (m != 1).any() and ((m[compute] == 1).any() or s == 'compute_half')}


def budget_power(nominal, activity, eligible):
    """Water-fill the freed power onto eligible dies at full activity, each capped at BOOST x nominal."""
    power = nominal*activity
    free, open_ = nominal.sum() - power.sum(), (activity == 1) & eligible
    while free > 1e-9 and open_.any():
        room = np.where(open_, BOOST*nominal - power, 0.)
        share = np.where(open_, nominal, 0.)/nominal[open_].sum()*free
        add = np.minimum(share, room)
        power, free = power + add, free - add.sum()
        open_ &= room - add > 1e-12
    return power


def regret(length, peaks, base_best):
    length, peaks = np.asarray(length), np.asarray(peaks)
    within = np.flatnonzero(length <= CAP_FACTOR*length.min())
    best = int(within[np.argmin(peaks[within])])
    shortest = int(np.argmin(length))
    return dict(best=best, regret_k=float(peaks[base_best] - peaks[best]), lever_k=float(peaks[shortest] - peaks[best]),
                peak_at_base_best_c=float(peaks[base_best]))


def verdict(cases):
    """cases: list of {scenario: regret row} over the primary family. Frozen rule in the plan."""
    hit = sum(any(r['regret_k'] >= MEANINGFUL_K for r in c.values()) for c in cases)
    quiet = all(r['regret_k'] < RESOLUTION_K for c in cases for r in c.values())
    return 'worthwhile' if hit >= 3 else 'degenerate' if quiet else 'uncertain'


def peak(job):
    case_path, power, centre, rotation, gap_um, resolution = job
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    problem = replace(problem, power_w=np.asarray(power))
    return solve_peak(thermal_case_data(problem, Layout(centre, rotation), gap_um, resolution))['peak_power_layer_c']


def analyse(case_path, summary_path, layouts_path, workers):
    summary = json.loads(Path(summary_path).read_text())
    if sha256(Path(case_path).read_bytes()).hexdigest() != summary['case_sha256']:
        raise SystemExit(f'{case_path} is not the case the front was frozen on')
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    for p, i in zip(summary['front'], index):
        if abs(z['length_m'][i] - p['length_m']) > 1e-9 or abs(z['peak_c'][i] - p['peak_c']) > 1e-9:
            raise SystemExit(f'front point {i} does not match layouts.npz')
    nominal = problem.power_w
    powers = dict(nominal=nominal)
    for s, m in scenarios(problem.names).items():
        powers[f'budget/{s}'], powers[f'activity/{s}'] = budget_power(nominal, m, is_compute(problem.names)), nominal*m
    jobs = [(str(case_path), p, z['centre_um'][i], z['rotation_deg'][i], summary['gap_um'], summary['fv_resolution'])
            for p in powers.values() for i in index]
    with ProcessPoolExecutor(workers) as pool:
        solved = np.array(list(pool.map(peak, jobs, chunksize=4))).reshape(len(powers), len(index))
    peaks = dict(zip(powers, solved))
    if np.abs(peaks['nominal'] - [p['peak_c'] for p in summary['front']]).max() > 1e-6:
        raise SystemExit('re-solved nominal peaks differ from the frozen front')
    length = [p['length_m'] for p in summary['front']]
    base_best = regret(length, peaks['nominal'], 0)['best']
    rows = {s: dict(regret(length, p, base_best), power_w=float(powers[s].sum())) for s, p in peaks.items()}
    return dict(case=summary['case'], front_index=index, length_m=length, nominal_best=base_best,
                summary_sha256=sha256(Path(summary_path).read_bytes()).hexdigest(),
                power_w={s: p.tolist() for s, p in powers.items()}, peaks_c={s: p.tolist() for s, p in peaks.items()},
                scenarios=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=int, nargs='+', default=list(range(1, 11)))
    parser.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    parser.add_argument('--front-dir', type=Path, default=Path('results/front-gap0'))
    parser.add_argument('--summary-dir', type=Path, default=Path('docs/evidence/front-gap0'))
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    cases = []
    for n in args.cases:
        r = analyse(args.import_dir/f'Case{n}.json', args.summary_dir/f'case{n}-summary.json',
                    args.front_dir/f'case{n}'/'layouts.npz', args.workers)
        cases.append(r)
        print(r['case'], ' '.join(f"{s}:{v['regret_k']:.2f}" for s, v in r['scenarios'].items() if s != 'nominal'),
              flush=True)
    family = {f: [{s: v for s, v in c['scenarios'].items() if s.startswith(f + '/')} for c in cases]
              for f in ('budget', 'activity')}
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/workload-leverage-plan.md',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), idle=IDLE, boost=BOOST,
        cap_factor=CAP_FACTOR, meaningful_k=MEANINGFUL_K, resolution_k=RESOLUTION_K,
        verdict=verdict(family['budget']), activity_verdict=verdict(family['activity']), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
