"""Control: replay the separate designer's air search (cold_plate_joint.analyse, same seed) and ask whether
each joint winner would already have been an air-Pareto candidate, i.e. whether the gain is search luck.
Run from the repository root: PYTHONPATH=src:tools python tools/cold_plate_air_control.py (eex005; writes results/)."""
import json
import numpy as np

import frozen_front
from cold_plate_joint import STARTS, SEED, search
from chiplet_floorplanning.placement import Evaluator, Layout, pareto_front, sample_legal
from chiplet_floorplanning.placement.search import length_descent

def main():
    d = json.load(open('docs/evidence/cold-plate-joint-v1.json'))
    out = {}
    for c in d['cases']:
        n = int(c['case'][4:])
        if n not in (3, 5, 9, 10):
            continue
        f = frozen_front.load(f'results/physical-calibration/atplace-import-v1/Case{n}.json',
                              f'docs/evidence/front-gap0/case{n}-summary.json', f'results/front-gap0/case{n}/layouts.npz')
        problem, gap, res = f.problem, f.gap_um, f.resolution
        rng = np.random.default_rng(SEED)
        initial = [sample_legal(problem, gap, rng) for _ in range(STARTS)]
        initial += [length_descent(problem, sample_legal(problem, gap, rng), rng, gap) for _ in range(STARTS)]
        air_layouts, air_length, air_peak = search(problem, initial, list(c['caps_m'].values()), gap, res, 12, None)
        length, peak = np.r_[f.length_m, air_length], np.r_[f.peak_c, air_peak]
        keep = pareto_front(length, peak)
        if len(keep) != c['separate_layouts']:
            raise SystemExit(f'{c["case"]}: replayed separate set has {len(keep)} layouts, run had {c["separate_layouts"]}')
        rows = {}
        for cap, r in c['rows'].items():
            if r is None or r['joint_from'] != 'joint_search':
                continue
            joint = Layout(np.array(r['joint_centre_um']), np.array(r['joint_rotation_deg']))
            with Evaluator(problem, gap, res, 1) as e:
                air = float(e.peaks_c([joint])[0])
            ok = length[keep] <= c['caps_m'][cap] + 1e-12
            best = float(peak[keep][ok].min())
            rows[cap] = dict(gain_k=r['gain_k'], joint_air_c=air, separate_air_best_c=best, joint_minus_separate_air_k=air - best)
            print(c['case'], cap, {k: round(v, 2) for k, v in rows[cap].items()}, flush=True)
        out[c['case']] = rows
    json.dump(out, open('results/cold-plate-joint-air-control.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
