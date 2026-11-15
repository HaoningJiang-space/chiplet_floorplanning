"""Layout versus package leverage on the frozen reference fronts (plan: docs/package-leverage-plan.md).

Every front layout is re-solved under each declared package variant. Per variant: the layout lever
(peak of the shortest front layout minus the coolest front peak within 1.25 x Lmin), the package
shift at the base-best layout, and whether the best layout within that cap changes.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, solve_peak, thermal_case_data

VARIANTS = dict(base={}, h_half=dict(top_h_factor=.5), h_double=dict(top_h_factor=2.),
                tim_1=dict(tim_k=1.), tim_8=dict(tim_k=8.), spreader_0p5=dict(spreader_mm=.5),
                spreader_2=dict(spreader_mm=2.))
CAP_FACTOR = 1.25          # v2 middle peak-cap rule: L <= 1.25 x Lmin
RESOLUTION_K = 0.3         # declared resolution for lever changes and best-layout advantage
INTERACTION = 0.3          # relative lever change that counts as an interaction


def peak(job):
    case_path, centre, rotation, gap_um, resolution, package = job
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    return solve_peak(thermal_case_data(problem, Layout(centre, rotation), gap_um, resolution, package))[
        'peak_power_layer_c']


def leverage(length, peaks):
    """length (layouts,), peaks {variant: (layouts,)} -> per-variant lever, best layout and shifts."""
    length = np.asarray(length)
    within = length <= CAP_FACTOR*length.min()
    shortest = int(np.argmin(length))
    base = np.asarray(peaks['base'])
    base_best = int(np.flatnonzero(within)[np.argmin(base[within])])
    base_lever = base[shortest] - base[base_best]
    rows = {}
    for name, p in peaks.items():
        p = np.asarray(p)
        best = int(np.flatnonzero(within)[np.argmin(p[within])])
        lever = p[shortest] - p[best]
        advantage = p[base_best] - p[best]
        interaction = (lever - base_lever)/base_lever if base_lever > 0 else None
        rows[name] = dict(lever_k=float(lever), full_lever_k=float(p[shortest] - p.min()), best=best,
                          best_changed=bool(best != base_best and advantage > RESOLUTION_K),
                          advantage_k=float(advantage), package_shift_k=float(p[base_best] - base[base_best]),
                          lever_change_k=float(lever - base_lever), relative_lever_change=interaction,
                          interacting=bool(abs(lever - base_lever) >= RESOLUTION_K and interaction is not None
                                           and abs(interaction) >= INTERACTION))
    return rows


def verdict(cases):
    """cases: list of leverage() outputs. Frozen rule in docs/package-leverage-plan.md."""
    hit = [any(r['interacting'] or r['best_changed'] for r in c.values()) for c in cases]
    quiet = all(abs(r['lever_change_k']) < RESOLUTION_K and not r['best_changed'] for c in cases for r in c.values())
    return 'worthwhile' if sum(hit) >= 3 else 'degenerate' if quiet else 'uncertain'


def analyse(case_path, summary_path, layouts_path, workers):
    summary = json.loads(Path(summary_path).read_text())
    if sha256(Path(case_path).read_bytes()).hexdigest() != summary['case_sha256']:
        raise SystemExit(f'{case_path} is not the case the front was frozen on')
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    for p, i in zip(summary['front'], index):
        if abs(z['length_m'][i] - p['length_m']) > 1e-9 or abs(z['peak_c'][i] - p['peak_c']) > 1e-9:
            raise SystemExit(f'front point {i} does not match layouts.npz')
    jobs = [(str(case_path), z['centre_um'][i], z['rotation_deg'][i], summary['gap_um'], summary['fv_resolution'], v)
            for v in VARIANTS.values() for i in index]
    with ProcessPoolExecutor(workers) as pool:
        solved = np.array(list(pool.map(peak, jobs, chunksize=4))).reshape(len(VARIANTS), len(index))
    peaks = dict(zip(VARIANTS, solved))
    if np.abs(peaks['base'] - [p['peak_c'] for p in summary['front']]).max() > 1e-6:
        raise SystemExit('re-solved base peaks differ from the frozen front')
    length = [p['length_m'] for p in summary['front']]
    return dict(case=summary['case'], front_index=index, length_m=length,
                summary_sha256=sha256(Path(summary_path).read_bytes()).hexdigest(),
                peaks_c={k: v.tolist() for k, v in peaks.items()}, variants=leverage(length, peaks))


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
        print(r['case'], ' '.join(f"{k}:lever {v['lever_k']:.2f} shift {v['package_shift_k']:+.2f}"
                                  f"{' I' if v['interacting'] else ''}{' B' if v['best_changed'] else ''}"
                                  for k, v in r['variants'].items()), flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/package-leverage-plan.md',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), variants=VARIANTS,
        cap_factor=CAP_FACTOR, resolution_k=RESOLUTION_K, interaction=INTERACTION,
        verdict=verdict([c['variants'] for c in cases]), cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
