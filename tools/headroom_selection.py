"""Rank common legal chiplet moves before observing their fine-grid temperatures."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.special import k0

from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import die_peaks_c
from physics_checks import KT_W_K, lambda_theory_mm


def length_m(problem, layout):
    return float(pin_manhattan_um(problem, layout).sum() / 1e6)


def conditions(problem):
    h = problem.top_h_w_m2k or 1 / (0.1 * 0.06**2)
    nominal = replace(problem, top_h_w_m2k=h)
    power = problem.power_w.copy()
    receiver, donor = np.argsort(-power, kind='stable')[:2]
    transfer = power[donor] / 4
    power[donor] -= transfer
    power[receiver] += transfer
    return dict(nominal=nominal, stronger_sink=replace(nominal, top_h_w_m2k=2*h),
                shifted_power=replace(nominal, power_w=power))


def coupling_rise(problem, layout):
    separation_mm = np.linalg.norm(layout.centre_um[:, None] - layout.centre_um[None, :], axis=2) / 1000
    np.fill_diagonal(separation_mm, np.inf)
    return (k0(separation_mm / lambda_theory_mm(problem.top_h_w_m2k)) @ problem.power_w) / (2*np.pi*KT_W_K)


def move_layout(parent, move):
    kind, *args = move
    centres = parent.centre_um.copy()
    if kind == 'single':
        die, axis, step_um = args
        centres[die, axis] += step_um
    elif kind == 'swap':
        a, b = args
        centres[[a, b]] = centres[[b, a]]
    elif kind == 'whole':
        axis, step_um = args
        centres[:, axis] += step_um
    elif kind != 'parent':
        raise ValueError(kind)
    return replace(parent, centre_um=centres)


def candidate_set(problem, parent, gap_um, cap_m, seed):
    single = [('single', i, a, d) for i in range(problem.count) for a in (0, 1)
              for d in (-2000, -500, 500, 2000)]
    size = np.where((parent.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    swaps = [('swap', i, j) for i in range(problem.count) for j in range(i)
             if problem.power_w[i] != problem.power_w[j] and np.array_equal(size[i], size[j])]
    whole = [('whole', a, d) for a in (0, 1) for d in (-2000, 2000)]
    moves = [('parent',)]
    lengths = [length_m(problem, parent)]
    rng = np.random.default_rng(seed)
    for family, limit in ((single, 18), (swaps, 8), (whole, 4)):
        legal = []
        for move in family:
            layout = move_layout(parent, move)
            if is_legal(problem, layout, gap_um):
                wire = length_m(problem, layout)
                if wire <= cap_m + 1e-9:
                    legal.append((move, wire))
        take = sorted(rng.choice(len(legal), limit, replace=False)) if len(legal) > limit else range(len(legal))
        for idx in take:
            move, wire = legal[idx]
            moves.append(move)
            lengths.append(wire)
    return moves, lengths


def temperature(job):
    problem, layout, gap_um, check96 = job
    result = {}
    for condition, p in conditions(problem).items():
        levels = (16, 64, 96) if condition == 'nominal' and check96 else (16, 64)
        values = {}
        for level in levels:
            start = perf_counter()
            state, field, edges = solve(thermal_case_data(p, layout, gap_um, level))
            peaks = die_peaks_c(p, layout, field, edges)
            assert abs(max(peaks) - state['peak_power_layer_c']) < 1e-7
            values[str(level)] = dict(peak_c=float(max(peaks)), die_c=peaks.tolist() if level == 64 else None,
                                      energy_error_w=state['energy_balance_error_w'], seconds=perf_counter()-start)
        result[condition] = values
    return result


def select(scores, lengths, parent_c):
    # Integer-scale ties prevent roundoff on rigid translations from deciding the result.
    def key(i):
        return round(scores[i], 9), round(lengths[i], 9), i
    coolest = min(range(len(scores)), key=key)
    eligible = (i for i in range(len(scores)) if scores[i] <= parent_c + 1e-9)
    shortest = min(eligible, key=lambda i: (round(lengths[i], 9), i))
    return dict(coolest=coolest, shortest=shortest)


def score_group(p, layouts, lengths, measured, condition):
    parent = np.array(measured[0][condition]['64']['die_c'])
    hottest = int(np.argmax(parent))
    base_rise = coupling_rise(p, layouts[0])
    forecast = np.array([parent + (coupling_rise(p, layout) - base_rise) for layout in layouts])
    peak64 = np.array([r[condition]['64']['peak_c'] for r in measured])
    coarse = np.array([r[condition]['16']['peak_c'] for r in measured])
    scores = dict(old_hot=forecast[:, hottest], all_dies=forecast.max(axis=1),
                  coarse=peak64[0] + (coarse - coarse[0]), oracle64=peak64)
    shortest = min(range(len(lengths)), key=lambda i: (round(lengths[i], 9), i))
    choices = dict(parent=dict(coolest=0, shortest=0), wire=dict(coolest=shortest, shortest=shortest))
    for key, values in scores.items():
        choices[key] = select(values, lengths, peak64[0])
    if '96' in measured[0][condition]:
        fine = [r[condition]['96']['peak_c'] for r in measured]
        choices['oracle96'] = select(fine, lengths, fine[0])
    return dict(h_w_m2k=p.top_h_w_m2k, power_w=p.power_w.tolist(), hot=hottest, choices=choices,
                scores_c={k: x.tolist() for k, x in scores.items()})


def run_case(case_file, directory, pool, ordinal):
    summary = json.loads((directory/'summary.json').read_text())
    blob = case_file.read_bytes()
    assert sha256(blob).hexdigest() == summary['case_sha256'] and summary['fv_resolution'] == 64
    problem = Problem.from_imported(json.loads(blob))
    assert problem.limit_c is None
    with np.load(directory/'layouts.npz') as z:
        centre, turns, wire, peaks = (z[k] for k in ('centre_um', 'rotation_deg', 'length_m', 'peak_c'))
    front = summary['front']
    for row in front:
        i = row['index']
        assert abs(wire[i]-row['length_m']) < 1e-9 and abs(peaks[i]-row['peak_c']) < 1e-7
    short, long = min(r['length_m'] for r in front), max(r['length_m'] for r in front)
    groups = []
    cache = {}
    for budget, cap in [('tight', 1.25*short), ('span', max(1.25*short, (short+long)/2))]:
        ok = np.flatnonzero(np.isfinite(peaks) & np.isfinite(wire) & (wire <= cap + 1e-9))
        order = ok[np.argsort(peaks[ok], kind='stable')]
        ids = {}
        for kind, idx in [('cold', int(order[0])), ('median', int(order[len(order)//2]))]:
            ids.setdefault(idx, []).append(kind)
        for idx, kinds in ids.items():
            parent = Layout(centre[idx], turns[idx])
            assert is_legal(problem, parent, summary['gap_um']) and abs(length_m(problem, parent)-wire[idx]) < 1e-9
            moves, lengths = candidate_set(problem, parent, summary['gap_um'], cap, [1, ordinal, idx])
            layouts = [move_layout(parent, move) for move in moves]
            keys = [(l.centre_um.tobytes(), l.rotation_deg.tobytes()) for l in layouts]
            jobs = {k: (problem, l, summary['gap_um'], ordinal in (3, 9, 12))
                    for k, l in zip(keys, layouts) if k not in cache}
            cache.update(zip(jobs, pool.map(temperature, jobs.values(), chunksize=1)))
            measured = [cache[k] for k in keys]
            assert abs(measured[0]['nominal']['64']['peak_c'] - peaks[idx]) < 1e-6
            conditions_out = {name: score_group(p, layouts, lengths, measured, name)
                              for name, p in conditions(problem).items()}
            groups.append(dict(budget=budget, cap_m=cap, archive_id=idx, parent_kinds=kinds, moves=moves,
                               lengths_m=lengths, measured=measured, conditions=conditions_out))
    stats = {}
    for result in cache.values():
        for by_mesh in result.values():
            for mesh, row in by_mesh.items():
                s = stats.setdefault(mesh, dict(solves=0, solver_seconds=0., max_abs_balance_w=0.))
                s['solves'] += 1
                s['solver_seconds'] += row['seconds']
                s['max_abs_balance_w'] = max(s['max_abs_balance_w'], abs(row['energy_error_w']))
    return dict(case=summary['case'], names=problem.names, gap_um=summary['gap_um'], source_seed=summary['seed'],
                source_commit=summary['code_commit'], case_sha256=summary['case_sha256'],
                summary_sha256=sha256((directory/'summary.json').read_bytes()).hexdigest(),
                driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), groups=groups, accounting=stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    datasets = [(args.data/'physical-calibration/atplace-import-v1'/f'Case{i}.json', args.data/'rs-grb-v4'/f'case{i}')
                for i in range(1, 11)]
    for name in ('G1_h100_slack', 'G2_4gpu16hbm_slack'):
        datasets.append((args.data/'industrial-v1/cases'/(name+'.json'), args.data/'industrial-v1/runs'/name))
    with ProcessPoolExecutor(args.workers) as pool:
        for ordinal, (case, directory) in enumerate(datasets, 1):
            result = run_case(case, directory, pool, ordinal)
            (args.output/(result['case']+'.json')).write_text(json.dumps(result, allow_nan=False)+'\n')
            print(result['case'], len(result['groups']), result['accounting'], flush=True)


if __name__ == '__main__':
    main()
