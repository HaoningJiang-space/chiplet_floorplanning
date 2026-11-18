"""Bound the optimum over all chiplet coordinates and compare with feasible layouts."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, solve, thermal_case_data, pin_manhattan_um


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def measure(problem, layout, gap_um, resolution):
    nominal = thermal_case_data(problem, layout, gap_um, resolution)
    h = nominal['thermal']['top_h_w_m2k']
    rows = {}
    for factor in (1, 2, 4, 8):
        nominal['thermal']['top_h_w_m2k'] = h * factor
        metrics, _, _ = solve(nominal)
        rows[factor] = dict(peak_c=metrics['peak_power_layer_c'],
                            error_w=metrics['energy_balance_error_w'])
    return dict(length_m=float(pin_manhattan_um(problem, layout).sum()/1e6),
                total_w=float(problem.power_w.sum()), h_w_m2k=h, factors=rows)


def bound(problem, layout, gap_um):
    from global_heat_floor import floor_for_case
    return floor_for_case(problem, thermal_case_data(problem, layout, gap_um, 64))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('layouts', 'bounds'))
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = Path(__file__).resolve().parents[1]/'docs/evidence/headroom-selection-v1.json'
    driver = sha(Path(__file__))
    with ProcessPoolExecutor(args.workers) as pool:
        pending = {}
        for ref in json.loads(evidence.read_text())['records']:
            name = ref['case']
            if name.startswith('Case'):
                source = args.data/'physical-calibration/atplace-import-v1'/(name+'.json')
                run = args.data/'rs-grb-v4'/name.lower()
            else:
                source = args.data/'industrial-v1/cases'/(name+'.json')
                run = args.data/'industrial-v1/runs'/name
            assert sha(source) == ref['case_sha256'] and sha(run/'summary.json') == ref['summary_sha256']
            problem = Problem.from_imported(json.loads(source.read_text()))
            with np.load(run/'layouts.npz') as z:
                for j, group in enumerate(ref['groups']):
                    i = group['archive_id']
                    layout = Layout(z['centre_um'][i], z['rotation_deg'][i])
                    meta = dict(case=name, driver_sha256=driver, case_sha256=ref['case_sha256'],
                                summary_sha256=ref['summary_sha256'])
                    if args.stage == 'bounds':
                        if j == 0:
                            meta['bound_driver_sha256'] = sha(Path(__file__).with_name('global_heat_floor.py'))
                            pending[pool.submit(bound, problem, layout, ref['gap_um'])] = (name, meta, None)
                        continue
                    historic = next(p for p in group['scenarios']['nominal']['selected_points'] if p['index'] == 0)
                    for res in (64, 96):
                        job = pool.submit(measure, problem, layout, ref['gap_um'], res)
                        pending[job] = (f'{name}-{i}-{res}', dict(meta, archive_id=i, resolution=res,
                                            budget=group['budget'], budget_m=group['cap_m']), historic)
        for future in as_completed(pending):
            key, meta, historic = pending[future]
            row = dict(meta, **future.result())
            if historic:
                assert abs(historic['length_m']-row['length_m']) < 1e-9
                if row['resolution'] == 64:
                    assert abs(historic['peak64_c']-row['factors'][1]['peak_c']) < 1e-6
            (args.output/(key+'.json')).write_text(json.dumps(row, allow_nan=False)+'\n')
            print(key, flush=True)


if __name__ == '__main__':
    main()
