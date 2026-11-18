"""Recover pin length within an equivalence class of uniform thermal footprints."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, is_legal, solve, thermal_case_data
from headroom_selection import conditions, length_m


def move(layout, action):
    kind, i, n = action
    centres, turns = layout.centre_um.copy(), layout.rotation_deg.copy()
    if kind == 'rotate':
        turns[i] = (turns[i] + n) % 360
    elif kind == 'swap':
        centres[[i, n]] = centres[[n, i]]
        turns[[i, n]] = turns[[n, i]]
    else:
        raise ValueError(kind)
    return Layout(centres, turns)


def actions(problem):
    powers = np.stack([p.power_w for p in conditions(problem).values()])
    turns = []
    for i, (width, height) in enumerate(problem.size_um):
        for angle in ((90, 180, 270) if width == height else (180,)):
            turns.append(('rotate', i, angle))
    swaps = []
    contrasts = []
    for i, j in combinations(range(problem.count), 2):
        if np.array_equal(problem.size_um[i], problem.size_um[j]):
            distance = float(np.abs(powers[:, i] - powers[:, j]).max())
            if distance == 0:
                swaps.append(('swap', i, j))
            else:
                contrasts.append((distance, ('swap', i, j)))
    control = max(contrasts, key=lambda pair: pair[0])[1] if contrasts else None
    return turns, swaps, control


def refine(problem, base, options):
    current = base
    trace = []
    for _ in range(4):
        length = length_m(problem, current)
        if not options:
            break
        best, action = min(((length_m(problem, move(current, op)), op) for op in options),
                           key=lambda pair: round(pair[0], 12))
        if length - best <= 1e-6:
            break
        current = move(current, action)
        trace.append(dict(action=action, length_m=best))
    return current, trace


def field_check(reference, current):
    a, field, edges = reference
    b, trial, new_edges = current
    same_grid = all(np.array_equal(x, y) for x, y in zip(edges, new_edges))
    same_mask = same_grid and np.array_equal(np.isfinite(field), np.isfinite(trial))
    return dict(same_grid=same_grid, same_mask=same_mask,
                max_field_delta_k=float(np.nanmax(np.abs(field-trial))) if same_mask else None,
                peak_c=b['peak_power_layer_c'], delta_peak_k=b['peak_power_layer_c']-a['peak_power_layer_c'],
                balance_w=b['energy_balance_error_w'])


def run_parent(job):
    p, parent, gap_um, archive_id = job
    turns, swaps, control = actions(p)
    designs, traces = {}, {}
    for name, opts in [('rotation', turns), ('joint', turns+swaps)]:
        designs[name], traces[name] = refine(p, parent, opts)
    if control:
        designs['control'] = move(parent, control)
    states = {}
    for name, layout in designs.items():
        assert is_legal(p, layout, gap_um)
        states[name] = dict(length_m=length_m(p, layout), trace=traces.get(name),
                            control_action=control if name == 'control' else None, fields={})
    count = 0
    bases = {}
    for name, condition in conditions(p).items():
        ref = solve(thermal_case_data(condition, parent, gap_um, 64))
        count += 1
        cache = {(parent.centre_um.tobytes(), parent.rotation_deg.tobytes()): ref}
        bases[name] = dict(peak_c=ref[0]['peak_power_layer_c'], balance_w=ref[0]['energy_balance_error_w'])
        for method, layout in designs.items():
            key = layout.centre_um.tobytes(), layout.rotation_deg.tobytes()
            if key not in cache:
                cache[key] = solve(thermal_case_data(condition, layout, gap_um, 64))
                count += 1
            states[method]['fields'][name] = field_check(ref, cache[key])
    return dict(archive_id=archive_id, parent_length_m=length_m(p, parent), parent_fields=bases,
                rotation_options=len(turns), swap_options=len(swaps), solves64=count, states=states)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    paths = sorted(args.parents.glob('*.json'))
    if len(paths) != 12:
        raise ValueError('Expected all twelve primary case records')
    with ProcessPoolExecutor(args.workers) as pool:
        for path in paths:
            record = json.loads(path.read_text())
            name = record['case']
            if name.startswith('Case'):
                source = args.data/'physical-calibration/atplace-import-v1'/(name+'.json')
                run = args.data/'rs-grb-v4'/name.lower()
            else:
                source = args.data/'industrial-v1/cases'/(name+'.json')
                run = args.data/'industrial-v1/runs'/name
            blob = source.read_bytes()
            assert sha256(blob).hexdigest() == record['case_sha256']
            p = Problem.from_imported(json.loads(blob))
            parents = {}
            with np.load(run/'layouts.npz') as z:
                centres, turns = z['centre_um'], z['rotation_deg']
                for group in record['groups']:
                    idx = group['archive_id']
                    base = Layout(centres[idx], turns[idx])
                    assert abs(length_m(p, base)-group['lengths_m'][0]) < 1e-9
                    parents.setdefault((centres[idx].tobytes(), turns[idx].tobytes()), (p, base, record['gap_um'], idx))
            rows = list(pool.map(run_parent, parents.values()))
            out = dict(case=name, case_sha256=record['case_sha256'], parent_record_sha256=sha256(path.read_bytes()).hexdigest(),
                       driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), rows=rows)
            (args.output/path.name).write_text(json.dumps(out, allow_nan=False)+'\n')
            print(name, len(rows), sum(r['solves64'] for r in rows), flush=True)


if __name__ == '__main__':
    main()
