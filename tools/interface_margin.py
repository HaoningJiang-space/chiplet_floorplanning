"""Temperature-aware interface timing on the frozen reference fronts (plan: docs/interface-margin-plan.md).

Per net: D = (L + d0)(1 + gamma (T - 25 C)) in units of tau, L = pin Manhattan distance (mm),
T = mean of the two endpoint temperatures (FV power layer). Layout cost = max over nets.
Signoff cost puts every T at 125 C. A changed choice needs a > 1% actual-cost advantage.
"""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um, thermal_case_data
from chiplet_floorplanning.placement import thermal
import frozen_front

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
    front = frozen_front.load(case_path, summary_path, layouts_path)
    jobs = [(str(case_path), l.centre_um, l.rotation_deg, front.gap_um, front.resolution) for l in front.layouts]
    with ProcessPoolExecutor(workers) as pool:
        states = list(pool.map(net_state, jobs))
    length, temp = np.array([s[0] for s in states]), np.array([s[1] for s in states])
    pin_max, peak = np.array([s[2] for s in states]), np.array([s[3] for s in states])
    if np.abs(peak - front.peak_c).max() > 1e-6:
        raise SystemExit('re-solved peaks differ from the frozen front')
    if np.abs(length.sum(axis=1)/1000 - front.length_m).max() > 1e-6:
        raise SystemExit('re-computed lengths differ from the frozen front')
    grid = []
    for gamma in GAMMAS:
        for d0 in D0_MM:
            c = choice(length, temp, d0, gamma)
            grid.append(dict(gamma_per_k=gamma, d0_mm=d0, **{k: v for k, v in c.items() if k != 'recovery'},
                             recovery_range=[min(c['recovery']), max(c['recovery'])],
                             recovery_at_actual_best=c['recovery'][c['actual_best']],
                             recovery_at_signoff_best=c['recovery'][c['signoff_best']]))
    critical = np.argmax(length, axis=1)
    return dict(case=front.case, front_layouts=len(front.index), front_index=front.index,
                summary_sha256=front.summary_sha256,
                pin_max_c=pin_max.tolist(), length_m=front.length_m.tolist(), peak_c=peak.tolist(),
                max_net_mm=length.max(axis=1).tolist(),
                critical_net_temp_c=temp[np.arange(len(front.index)), critical].tolist(),
                share_above_signoff=float((pin_max > SIGNOFF_C).mean()),
                changed_gammas=sorted({g['gamma_per_k'] for g in grid if g['verdict'] == 'changed'}),
                grid=grid)


def main():
    args = frozen_front.arguments(__doc__)
    cases = []
    for n in args.cases:
        r = analyse(*frozen_front.paths(args, n), args.workers)
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
