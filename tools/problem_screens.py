"""Degeneracy screens for candidate problems (plan: docs/problem-screens-plan.md).

phy:   upper bound of the wire length saved if inter-chiplet PHYs could sit anywhere on the die edges - each net
       then needs only the Manhattan gap between the two die boxes - on front and random layouts.
scale: ATPlace cases with the carrier scaled by s on both sides, for the interposer-area screen.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from atplace_compare import pick
from chiplet_floorplanning.placement import Problem, boxes, pin_manhattan_um, sample_legal
import frozen_front

SCALES = (0.85, 0.92, 1.0, 1.1, 1.25)
RANDOM = 16


def box_gap_um(problem, layout):
    """Per net, the Manhattan gap between its two die boxes: the shortest a net can be with free edge PHYs."""
    b = boxes(problem, layout)
    i, j = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
    dx = np.maximum(0, np.maximum(b[i, 0], b[j, 0]) - np.minimum(b[i, 2], b[j, 2]))
    dy = np.maximum(0, np.maximum(b[i, 1], b[j, 1]) - np.minimum(b[i, 3], b[j, 3]))
    return dx + dy


def saving(problem, layout):
    pins = pin_manhattan_um(problem, layout).sum()
    return float(1 - box_gap_um(problem, layout).sum()/pins) if pins > 0 else 0.0


def phy(args):
    rng = np.random.default_rng(args.seed)
    rows = {}
    for n in args.cases:
        case = args.import_dir/f'Case{n}.json'
        front = frozen_front.load(case, args.runs/f'case{n}'/'summary.json', args.runs/f'case{n}'/'layouts.npz')
        keep = pick(front.length_m)
        on_front = np.array([saving(front.problem, front.layouts[i]) for i in keep])
        random = np.array([saving(front.problem, sample_legal(front.problem, front.summary['gap_um'], rng))
                           for _ in range(RANDOM)])
        rows[f'Case{n}'] = dict(front_median=float(np.median(on_front)), front_max=float(on_front.max()),
                                shortest=float(on_front[0]), coolest=float(on_front[int(np.argmin(front.peak_c[keep]))]),
                                random_median=float(np.median(random)))
        print(f'Case{n}', {k: round(v, 3) for k, v in rows[f'Case{n}'].items()}, flush=True)
    med = [r['front_median'] for r in rows.values()]
    verdict = ('not_degenerate' if sum(m >= 0.10 for m in med) >= 5 else
               'degenerate' if sum(m < 0.05 for m in med) >= 7 else 'uncertain')
    args.output.write_text(json.dumps(dict(plan='docs/problem-screens-plan.md', screen='phy', verdict=verdict,
                                           cases=rows), indent=1) + '\n')
    print(verdict)


def tag(s):
    """Scale label usable in case names (the thermal model's IDs allow no '.'): 0.92 -> s0p92."""
    return f's{s:g}'.replace('.', 'p')


def scaled_case(case, s):
    return dict(case, name=f"{case['name']}_{tag(s)}",
                interposer_width_um=round(case['interposer_width_um']*s, -1),
                interposer_height_um=round(case['interposer_height_um']*s, -1))


def scale(args):
    args.output.mkdir(parents=True, exist_ok=False)
    for n in args.cases:
        case = json.loads((args.import_dir/f'Case{n}.json').read_text())
        for s in SCALES:
            scaled = scaled_case(case, s)
            Problem.from_imported(scaled)
            (args.output/f'Case{n}_{tag(s)}.json').write_text(json.dumps(scaled) + '\n')
    print('written', len(args.cases)*len(SCALES))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('phy', 'scale'))
    p.add_argument('--cases', type=int, nargs='+', default=list(range(1, 11)))
    p.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    p.add_argument('--runs', type=Path, help='phy: run_reference_front outputs, caseN/{summary.json,layouts.npz}')
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    {'phy': phy, 'scale': scale}[args.command](args)


if __name__ == '__main__':
    main()
