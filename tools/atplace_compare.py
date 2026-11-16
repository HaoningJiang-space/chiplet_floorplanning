"""Head-to-head comparison with ATPlace2.5D (plan: docs/atplace-comparison-plan.md).

export:  16 frozen-front layouts per case (evenly by length) as ATPlace layout.json files, for ATSim on moe-server.
fv:      ATPlace layout.json files from the sweep, scored with our FV model and pin length (run on eex005).
compare: margin dominance of each side in both thermal models -> per-case outcome and the frozen verdict.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, Problem, is_legal, pin_manhattan_um
import frozen_front

PER_FRONT = 16
CASES = tuple(range(1, 11))


def to_atplace(problem, layout, case):
    """ATPlace layout.json fields read by its ATSim evaluation: centres, rotated sizes, power."""
    turned = layout.rotation_deg % 180 != 0
    size = np.where(turned[:, None], problem.size_um[:, ::-1], problem.size_um)
    width, height = problem.carrier_um
    return dict(case=case, mode='ours', unit='um',
                interposer=dict(width=width, height=height, fence=[0.0, width, 0.0, height]),
                chiplets=[dict(name=n, x=float(c[0]), y=float(c[1]), width=float(s[0]), height=float(s[1]),
                               angle_rad=float(np.radians(r)), power_w=float(p))
                          for n, c, s, r, p in zip(problem.names, layout.centre_um, size, layout.rotation_deg,
                                                   problem.power_w)])


def from_atplace(problem, data):
    """Our Layout from an ATPlace layout.json (centres in um, quarter-turn angles; same rotation sense)."""
    by = {c['name']: c for c in data['chiplets']}
    centre = np.array([[by[n]['x'], by[n]['y']] for n in problem.names], float)
    turns = np.array([np.degrees(by[n]['angle_rad']) / 90 for n in problem.names])
    if np.abs(turns - turns.round()).max() > 1e-4:
        raise ValueError('only quarter-turn rotations supported')
    return Layout(centre, (turns.round().astype(int) % 4) * 90)


def pick(lengths, k=PER_FRONT):
    order = np.argsort(lengths)
    return sorted({int(order[i]) for i in np.linspace(0, len(order) - 1, k).round().astype(int)})


def dominates(a, b):
    """Margin dominance of point a = (length, peak) over b: 1 K cooler at no more length, or 10% shorter at no more heat."""
    return (a[0] <= b[0] and a[1] <= b[1] - 1.0) or (a[0] <= 0.9 * b[0] and a[1] <= b[1])


def outcome(ours, atp):
    """Per case and thermal model: shares dominated by the other side, per-point gaps and the frozen outcome."""
    ours, atp = [tuple(p) for p in ours], [tuple(p) for p in atp]
    d_ours = sum(any(dominates(o, a) for o in ours) for a in atp) / len(atp)
    d_atp = sum(any(dominates(a, o) for a in atp) for o in ours) / len(ours)
    points = []
    for a in atp:
        cooler = [o[1] for o in ours if o[0] <= a[0]]
        shorter = [o[0] for o in ours if o[1] <= a[1]]
        points.append(dict(length_m=a[0], peak_c=a[1], delta_t_k=a[1] - min(cooler) if cooler else None,
                           delta_l_m=a[0] - min(shorter) if shorter else None))
    if d_ours >= 0.5 and d_atp <= 0.1:
        result = 'ours'
    elif d_atp >= 0.25 and d_ours < 0.5:
        result = 'atplace'
    else:
        result = 'tie'
    return dict(d_ours=d_ours, d_atp=d_atp, outcome=result, points=points)


def verdict(by_model):
    """by_model: {model: [per-case outcome dicts]} for the FV and ATSim models."""
    wins = {m: sum(c['outcome'] == 'ours' for c in cases) for m, cases in by_model.items()}
    losses = {m: sum(c['outcome'] == 'atplace' for c in cases) for m, cases in by_model.items()}
    if all(w >= 7 for w in wins.values()):
        return 'advantage', wins, losses
    if any(n >= 5 for n in losses.values()) or all(w <= 3 for w in wins.values()):
        return 'no_advantage', wins, losses
    return 'partial', wins, losses


def export(args):
    for n in args.cases:
        front = frozen_front.load(*frozen_front.paths(args, n))
        out = args.output / front.case
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for i in pick(front.length_m):
            name = f'k{i:03d}'
            (out / f'{name}.layout.json').write_text(json.dumps(to_atplace(front.problem, front.layouts[i], front.case)) + '\n')
            rows.append(dict(name=name, front_index=i, length_m=float(front.length_m[i]), fv_peak_c=float(front.peak_c[i])))
        (out / 'manifest.json').write_text(json.dumps(rows, indent=1) + '\n')
        print(front.case, len(rows), flush=True)


def fv(args):
    out = {}
    for n in args.cases:
        case = f'Case{n}'
        problem = Problem.from_imported(json.loads((args.import_dir / f'{case}.json').read_text()))
        gap = json.loads((args.summary_dir / f'case{n}-summary.json').read_text())['gap_um']
        rows = []
        for path in sorted((args.sweep / case).glob('*/layout.json')):
            layout = from_atplace(problem, json.loads(path.read_text()))
            row = dict(label=path.parent.name, length_m=float(pin_manhattan_um(problem, layout).sum() / 1e6),
                       legal=bool(is_legal(problem, layout, gap)))
            if row['legal']:
                with Evaluator(problem, gap, args.resolution) as evaluator:
                    row['fv_peak_c'] = float(evaluator.peaks_c([layout])[0])
            rows.append(row)
        out[case] = rows
        print(case, [(r['label'], round(r['length_m'], 2), r.get('fv_peak_c') and round(r['fv_peak_c'], 2)) for r in rows],
              flush=True)
    args.output.write_text(json.dumps(out, indent=1) + '\n')


def compare(args):
    fvs = json.loads(args.atplace_fv.read_text())
    by_model, cases = {'fv': [], 'atsim': []}, []
    for n in args.cases:
        case = f'Case{n}'
        mine = json.loads((args.ours / case / 'manifest.json').read_text())
        for r in mine:
            r['atsim_peak_c'] = json.loads((args.ours / case / f"{r['name']}.atsim.json").read_text())['tmax_c']
        theirs = [r for r in fvs[case] if r['legal']]
        for r in theirs:
            r['atsim_peak_c'] = json.loads((args.sweep / case / r['label'] / 'atsim.json').read_text())['tmax_c']
        row = dict(case=case, ours=mine, atplace=theirs)
        for model, key in (('fv', 'fv_peak_c'), ('atsim', 'atsim_peak_c')):
            row[model] = outcome([(r['length_m'], r[key]) for r in mine], [(r['length_m'], r[key]) for r in theirs])
            by_model[model].append(row[model])
        cases.append(row)
        print(case, {m: (row[m]['outcome'], round(row[m]['d_ours'], 2), round(row[m]['d_atp'], 2)) for m in by_model},
              flush=True)
    result, wins, losses = verdict(by_model)
    args.output.write_text(json.dumps(dict(physical_qualified=False, plan='docs/atplace-comparison-plan.md',
                                           verdict=result, wins=wins, losses=losses, cases=cases), indent=1) + '\n')
    print(result, wins, losses)


def main():
    p = frozen_front.parser(__doc__, CASES)
    p.add_argument('command', choices=('export', 'fv', 'compare'))
    p.add_argument('--sweep', type=Path, help='ATPlace sweep directory: CaseN/<label>/{layout,atsim}.json')
    p.add_argument('--ours', type=Path, help='exported layouts: CaseN/{manifest.json,kXXX.*}')
    p.add_argument('--atplace-fv', type=Path, help='output of the fv command')
    p.add_argument('--resolution', type=int, default=64)
    args = p.parse_args()
    {'export': export, 'fv': fv, 'compare': compare}[args.command](args)


if __name__ == '__main__':
    main()
