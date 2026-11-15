"""Temperature-aware interface timing on the frozen reference fronts (plan: docs/interface-margin-plan.md).

Per net: D = (L + d0)(1 + gamma (T - 25 C)) in units of tau, L = pin Manhattan distance (mm),
T = mean of the two endpoint temperatures (FV power layer). Layout cost = max over nets.
Signoff cost puts every T at 125 C. A changed choice needs a > 1% actual-cost advantage.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um, thermal_case_data
from chiplet_floorplanning.placement import thermal

GAMMAS = (-0.001, 0.0, 0.001, 0.002, 0.003, 0.004)  # per K
D0_MM = (0.0, 2.0, 5.0)
REFERENCE_C, SIGNOFF_C, RESOLUTION = 25.0, 125.0, 0.01


def net_state(job):
    """Per-net length (mm) and mean endpoint temperature (C) of one layout."""
    case_path, centre, rotation, gap_um, resolution = job
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    layout = Layout(centre, rotation)
    summary, rise, edges = thermal.solve(thermal_case_data(problem, layout, gap_um, resolution))
    pins = thermal.pin_temperatures_c(problem, layout, rise, edges)
    return pin_manhattan_um(problem, layout)/1000, pins.mean(axis=1), float(pins.max()), summary['peak_power_layer_c']


def cost(length, temp, d0, gamma):
    """Critical-net delay (units of tau) of each layout; length/temp have shape (layouts, nets)."""
    return ((length + d0)*(1 + gamma*(temp - REFERENCE_C))).max(axis=1)


def choice(length, temp, d0, gamma):
    actual = cost(length, temp, d0, gamma)
    signoff = cost(length, np.full_like(temp, SIGNOFF_C), d0, gamma)
    a, b = int(np.argmin(actual)), int(np.argmin(signoff))
    advantage = (actual[b] - actual[a])/actual[b]
    return dict(actual_best=a, signoff_best=b, advantage=float(advantage),
                verdict='unchanged' if a == b else 'changed' if advantage > RESOLUTION else 'indistinguishable',
                recovery=(1 - actual/signoff).tolist())


def analyse(case_path, summary_path, layouts_path, workers):
    summary = json.loads(Path(summary_path).read_text())
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    for p, i in zip(summary['front'], index):
        if abs(z['length_m'][i] - p['length_m']) > 1e-9 or abs(z['peak_c'][i] - p['peak_c']) > 1e-9:
            raise SystemExit(f'front point {i} does not match layouts.npz')
    jobs = [(str(case_path), z['centre_um'][i], z['rotation_deg'][i], summary['gap_um'], summary['fv_resolution'])
            for i in index]
    with ProcessPoolExecutor(workers) as pool:
        states = list(pool.map(net_state, jobs))
    length, temp = np.array([s[0] for s in states]), np.array([s[1] for s in states])
    pin_max, peak = np.array([s[2] for s in states]), np.array([s[3] for s in states])
    if np.abs(peak - [p['peak_c'] for p in summary['front']]).max() > 1e-6:
        raise SystemExit('re-solved peaks differ from the frozen front')
    grid = []
    for gamma in GAMMAS:
        for d0 in D0_MM:
            c = choice(length, temp, d0, gamma)
            grid.append(dict(gamma_per_k=gamma, d0_mm=d0, **{k: v for k, v in c.items() if k != 'recovery'},
                             recovery_range=[min(c['recovery']), max(c['recovery'])],
                             recovery_at_actual_best=c['recovery'][c['actual_best']],
                             recovery_at_signoff_best=c['recovery'][c['signoff_best']]))
    critical = np.argmax(length, axis=1)
    return dict(case=summary['case'], front_layouts=len(index), front_index=index,
                summary_sha256=sha256(Path(summary_path).read_bytes()).hexdigest(),
                pin_max_c=pin_max.tolist(), length_m=[p['length_m'] for p in summary['front']], peak_c=peak.tolist(),
                max_net_mm=length.max(axis=1).tolist(),
                critical_net_temp_c=temp[np.arange(len(index)), critical].tolist(),
                share_above_signoff=float((pin_max > SIGNOFF_C).mean()),
                changed_gammas=sorted({g['gamma_per_k'] for g in grid if g['verdict'] == 'changed'}),
                grid=grid)


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
        print(r['case'], len(r['front_index']), 'above 125C %.2f' % r['share_above_signoff'],
              'changed at', r['changed_gammas'], flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/interface-margin-plan.md',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        model='D = (L + d0)(1 + gamma (T - 25 C)), T = mean endpoint temperature, cost = max over nets',
        gammas_per_k=GAMMAS, d0_mm=D0_MM, signoff_c=SIGNOFF_C, resolution=RESOLUTION, cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
