"""Compare equal opposite moves of one non-hot die around an archived layout."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

import frozen_front
from chiplet_floorplanning.placement import is_legal, pin_manhattan_um, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import die_peaks_c


def thermal(problem, layout, gap_um, resolution):
    state, rise, edges = solve(thermal_case_data(problem, layout, gap_um, resolution))
    peaks = die_peaks_c(problem, layout, rise, edges)
    hot = int(np.argmax(peaks))
    assert abs(peaks[hot] - state['peak_power_layer_c']) < 1e-7
    return dict(peak_c=float(peaks[hot]), hot=hot, balance_error_w=state['energy_balance_error_w'])


def trial_layout(parent, die, axis, shift_um):
    centres = parent.centre_um.copy()
    centres[die, axis] += shift_um
    return replace(parent, centre_um=centres)


def pairs(problem, parent, hot, gap_um, cap_m, step_um):
    for die in range(problem.count):
        if die == hot:
            continue
        for axis in (0, 1):
            offset = parent.centre_um[die, axis] - parent.centre_um[hot, axis]
            # With the orthogonal offset fixed, strict approach requires |a - step| < a.
            if abs(offset) <= step_um / 2:
                continue
            away_um = int(np.sign(offset)) * step_um
            lengths = {}
            for side, sign in (('near', -1), ('far', 1)):
                layout = trial_layout(parent, die, axis, sign * away_um)
                if not is_legal(problem, layout, gap_um):
                    break
                length_m = float(pin_manhattan_um(problem, layout).sum()) / 1e6
                if length_m > cap_m + 1e-9:
                    break
                lengths[side + '_length_m'] = length_m
            if len(lengths) == 2:
                yield dict(die=die, axis=axis, away_um=away_um, **lengths)


def evaluate_pair(args):
    problem, parent, gap_um, pair, resolution = args
    result = pair.copy()
    for side, sign in (('near', -1), ('far', 1)):
        moved = trial_layout(parent, pair['die'], pair['axis'], sign * pair['away_um'])
        result[side] = thermal(problem, moved, gap_um, resolution)
    result['gain_k'] = result['near']['peak_c'] - result['far']['peak_c']
    return result


def lowest_wire(rows, side, peak_cap_c):
    eligible = [r for r in rows if r[side]['peak_c'] <= peak_cap_c + 1e-9]
    if not eligible:
        return None
    best = min(eligible, key=lambda r: r[side + '_length_m'])
    return dict(die=best['die'], axis=best['axis'], away_um=best['away_um'],
                length_m=best[side + '_length_m'], peak_c=best[side]['peak_c'])


def selected_parents(front):
    shortest = int(np.argmin(front.length_m))
    selected = {shortest: ['shortest']}
    for ratio in (1.125, 1.25):
        allowed = np.flatnonzero(front.length_m <= ratio * front.length_m[shortest] + 1e-9)
        index = int(allowed[np.argmin(front.peak_c[allowed])])
        selected.setdefault(index, []).append(str(ratio))
    return selected


def run_case(case_file, run_dir, pool):
    front = frozen_front.load(case_file, run_dir / 'summary.json', run_dir / 'layouts.npz')
    assert front.resolution == 64 and front.problem.limit_c is None
    problem = front.problem
    cap_m = 1.25 * float(front.length_m.min())
    parents = []
    layouts = {}
    for idx, labels in selected_parents(front).items():
        layout = front.layouts[idx]
        archive_id = int(front.index[idx])
        layouts[archive_id] = layout
        base = thermal(problem, layout, front.gap_um, 64)
        assert abs(base['peak_c'] - front.peak_c[idx]) < 1e-6
        root = dict(archive_id=archive_id, labels=labels, length_m=float(front.length_m[idx]),
                    base=base, steps={})
        for step_um in (1000, 500):
            jobs = [(problem, layout, front.gap_um, p, 64)
                    for p in pairs(problem, layout, base['hot'], front.gap_um, cap_m, step_um)]
            rows = list(pool.map(evaluate_pair, jobs, chunksize=2))
            root['steps'][str(step_um)] = dict(pairs=rows, shortest_within_parent_peak={
                side: lowest_wire(rows, side, base['peak_c']) for side in ('near', 'far')})
        parents.append(root)

    primary = [(r, p['archive_id']) for p in parents for r in p['steps']['1000']['pairs']]
    fine = []
    fine_bases = {}
    for label, sign in (('largest_benefit', 1), ('largest_reversal', -1)):
        if not primary:
            continue
        row, archive_id = max(primary, key=lambda item: sign * item[0]['gain_k'])
        if sign * row['gain_k'] < 0.1:
            continue
        layout = layouts[archive_id]
        if archive_id not in fine_bases:
            fine_bases[archive_id] = thermal(problem, layout, front.gap_um, 96)
        move = {k: row[k] for k in ('die', 'axis', 'away_um', 'near_length_m', 'far_length_m')}
        fine.append(dict(reason=label, archive_id=archive_id, base=fine_bases[archive_id],
                         coarse_gain_k=row['gain_k'], pair=evaluate_pair((problem, layout, front.gap_um, move, 96))))
    return dict(case=front.case, names=problem.names, gap_um=front.gap_um, cap_m=cap_m,
                seed=front.summary['seed'], front_commit=front.summary['code_commit'],
                case_sha256=front.summary['case_sha256'],
                summary_sha256=sha256((run_dir / 'summary.json').read_bytes()).hexdigest(),
                driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                parents=parents, fine=fine, fine_parent_solves=len(fine_bases))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='Server results directory')
    parser.add_argument('--output', type=Path, required=True, help='New directory for paired observations')
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = [(args.data / 'physical-calibration/atplace-import-v1' / f'Case{n}.json',
              args.data / 'rs-grb-v4' / f'case{n}') for n in range(1, 11)]
    industrial = args.data / 'industrial-v1'
    for name in ('G1_h100_slack', 'G2_4gpu16hbm_slack'):
        cases.append((industrial / 'cases' / (name + '.json'), industrial / 'runs' / name))
    with ProcessPoolExecutor(args.workers) as pool:
        for case_file, run_dir in cases:
            data = run_case(case_file, run_dir, pool)
            (args.output / (data['case'] + '.json')).write_text(json.dumps(data, indent=1) + '\n')
            counts = [sum(len(p['steps'][str(s)]['pairs']) for p in data['parents']) for s in (1000, 500)]
            print(data['case'], 'parents', len(data['parents']), 'pairs 1/0.5 mm', *counts, flush=True)


if __name__ == '__main__':
    main()
