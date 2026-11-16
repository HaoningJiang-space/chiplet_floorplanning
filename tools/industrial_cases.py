"""Industrial cases G1 (H100 class) and G2 (4 GPU + 16 HBM + 2 IO class) (plan: docs/industrial-cases-plan.md).

build:  case JSONs for the tight and slack carriers, each with the photo hand layout and the sink-top h calibrated so
        that the hand layout's hottest GPU is at 85 C; the method then runs on them with tools/run_reference_front.py.
assess: each front against its hand layout -> dT, dL and the frozen outcome.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, Problem, is_legal, pin_manhattan_um, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import die_peaks_c
import frozen_front

GAP_UM = 200.0                      # IHP Open-ADK ASM.b
GB_S_PER_NET = 20.0
T_CAL_C = 85.0
MARGIN_UM = 800.0                   # per side, tight carrier without a size estimate
SLACK = 1.15
RESOLUTION = 64
GPU_UM, HBM_UM, IO_UM = (26000.0, 31300.0), (11000.0, 11000.0), (26000.0, 12000.0)
HBM_PIN = (HBM_UM[0]/2, 0.0)        # middle of one HBM edge; the hand layout turns it to face its GPU
SIDE_UM = GPU_UM[0]/2 + GAP_UM + HBM_UM[0]/2


def g1():
    """H100 class: GPU in the middle, three HBM3 stacks per side, the lower right one a dummy (no power, no links)."""
    rows = (-(HBM_UM[1] + GAP_UM), 0.0, HBM_UM[1] + GAP_UM)
    dies = [('GPU', GPU_UM, 540.0, (0.0, 0.0), 0)]
    links = []
    for k, y in enumerate(rows):
        dies.append((f'HBM_L{k}', HBM_UM, 22.0, (-SIDE_UM, y), 0))
        links.append(('GPU', (-GPU_UM[0]/2, y), f'HBM_L{k}', HBM_PIN, 670.0))
    for k, y in enumerate(rows[:0:-1]):
        dies.append((f'HBM_R{k}', HBM_UM, 22.0, (SIDE_UM, y), 180))
        links.append(('GPU', (GPU_UM[0]/2, y), f'HBM_R{k}', HBM_PIN, 670.0))
    dies.append(('HBM_DUMMY', HBM_UM, 0.0, (SIDE_UM, rows[0]), 0))
    return dict(name='G1_h100', dies=dies, links=links, tight_um=(50000.0, 48000.0))


def g2():
    """Four GPUs in a column (short edges facing), an IO die at each end, two HBM4E stacks on each long GPU edge."""
    pitch, slot = GPU_UM[1] + GAP_UM, HBM_UM[1]/2 + GAP_UM/2
    gpu_y = [(k - 1.5)*pitch for k in range(4)]
    io_y = gpu_y[-1] + GPU_UM[1]/2 + GAP_UM + IO_UM[1]/2
    top, io_pin = (0.0, GPU_UM[1]/2), (0.0, IO_UM[1]/2)
    dies, links = [], []
    for k, y in enumerate(gpu_y):
        dies.append((f'GPU{k}', GPU_UM, 750.0, (0.0, y), 0))
        for side, x, turn in (('L', -1, 0), ('R', 1, 180)):
            for j, dy in enumerate((-slot, slot)):
                dies.append((f'HBM{k}{side}{j}', HBM_UM, 25.0, (x*SIDE_UM, y + dy), turn))
                links.append((f'GPU{k}', (x*GPU_UM[0]/2, dy), f'HBM{k}{side}{j}', HBM_PIN, 2000.0))
        if k:
            links.append((f'GPU{k - 1}', top, f'GPU{k}', (0.0, -top[1]), 10000.0))
    dies += [('IO_A', IO_UM, 60.0, (0.0, -io_y), 0), ('IO_B', IO_UM, 60.0, (0.0, io_y), 180)]
    links += [(f'GPU{k}', (0.0, -top[1]), 'IO_A', io_pin, 1800.0) for k in (0, 1)]
    links += [(f'GPU{k}', top, 'IO_B', io_pin, 1800.0) for k in (2, 3)]
    return dict(name='G2_4gpu16hbm', dies=dies, links=links, tight_um=None)


def footprint(dies):
    """(width, height) of the hand layout's bounding box, um."""
    lo, hi = np.full(2, np.inf), np.full(2, -np.inf)
    for _, size, _, centre, turn in dies:
        half = np.array(size[::-1] if turn % 180 else size)/2
        lo, hi = np.minimum(lo, np.array(centre) - half), np.maximum(hi, np.array(centre) + half)
    return hi - lo


def case_json(spec, carrier):
    nets = [dict(pins=[dict(chiplet=a, offset_x_um_decimal=pa[0], offset_y_um_decimal=pa[1]),
                       dict(chiplet=b, offset_x_um_decimal=pb[0], offset_y_um_decimal=pb[1])])
            for a, pa, b, pb, gb_s in spec['links'] for _ in range(round(gb_s/GB_S_PER_NET))]
    centre = np.array(carrier)/2
    return dict(name=spec['name'], plan='docs/industrial-cases-plan.md', gap_um=GAP_UM,
                interposer_width_um=float(carrier[0]), interposer_height_um=float(carrier[1]),
                chiplets=[dict(name=n, width_um=s[0], height_um=s[1], power_w_decimal=p) for n, s, p, _, _ in spec['dies']],
                nets=nets,
                hand_layout=dict(centre_um=[list(centre + c) for _, _, _, c, _ in spec['dies']],
                                 rotation_deg=[t for *_, t in spec['dies']]))


def hand_layout(case):
    return Layout(np.array(case['hand_layout']['centre_um']), np.array(case['hand_layout']['rotation_deg']))


def gpu_peak_c(problem, layout, top_h):
    _, rise, edges = solve(thermal_case_data(problem, layout, GAP_UM, RESOLUTION, top_h_w_m2k=top_h))
    peaks = die_peaks_c(problem, layout, rise, edges)
    return max(t for n, t in zip(problem.names, peaks) if n.startswith('GPU'))


def calibrate_h(problem, layout, low=50.0, high=1e6, iterations=40):
    """Sink-top h (W/m^2K) at which the hand layout's hottest GPU is at T_CAL_C (bisection in log h)."""
    for _ in range(iterations):
        mid = np.sqrt(low*high)
        if gpu_peak_c(problem, layout, mid) > T_CAL_C:
            low = mid
        else:
            high = mid
    return float(np.sqrt(low*high))


def build(args):
    args.output.mkdir(parents=True, exist_ok=False)
    for spec in (g1(), g2()):
        tight = spec['tight_um'] or tuple(footprint(spec['dies']) + 2*MARGIN_UM)
        for label, carrier in (('tight', tight), ('slack', tuple(np.round(np.array(tight)*SLACK, -1)))):
            case = case_json(spec, carrier)
            case['name'] = f"{spec['name']}_{label}"
            problem, layout = Problem.from_imported(case), hand_layout(case)
            if not is_legal(problem, layout, GAP_UM):
                raise SystemExit(f"{case['name']}: hand layout is illegal")
            case['top_h_w_m2k'] = calibrate_h(problem, layout)
            (args.output/f"{case['name']}.json").write_text(json.dumps(case, indent=1) + '\n')
            print(case['name'], 'carrier mm', [c/1000 for c in carrier], 'nets', len(case['nets']),
                  'h', round(case['top_h_w_m2k']), flush=True)


def outcome(front, hand):
    """Front [(length, peak)] against the hand point (L_h, T_h): dT, dL and the frozen outcome."""
    length_h, peak_h = hand
    cool = [t for l, t in front if l <= length_h]
    short = [l for l, t in front if t <= peak_h]
    d_t = peak_h - min(cool) if cool else None
    d_l = 1 - min(short)/length_h if short else None
    if (d_t is not None and d_t >= 1.0) or (d_l is not None and d_l >= 0.1):
        verdict = 'better'
    elif any(l <= 1.01*length_h and t <= peak_h + 0.5 for l, t in front):
        verdict = 'recovered'
    else:
        verdict = 'worse'
    return dict(d_t_k=d_t, d_l=d_l, outcome=verdict)


def hbm_link_mm(problem, layout):
    """Longest net with an HBM end, mm."""
    hbm = np.array([n.startswith('HBM') for n in problem.names])[problem.pin_chip].any(axis=1)
    return float(pin_manhattan_um(problem, layout)[hbm].max()/1000)


def assess(args):
    out = {}
    for path in sorted(args.cases.glob('*.json')):
        case = json.loads(path.read_text())
        run = args.runs/case['name']
        front = frozen_front.load(path, run/'summary.json', run/'layouts.npz')
        problem, hand = front.problem, hand_layout(case)
        with Evaluator(problem, GAP_UM, RESOLUTION) as evaluator:
            peak_h = float(evaluator.peaks_c([hand])[0])
            die_h = dict(zip(problem.names, map(float, evaluator.die_peaks_c([hand])[0])))
        length_h = float(pin_manhattan_um(problem, hand).sum()/1e6)
        points = list(zip(front.length_m, front.peak_c))
        row = dict(hand=dict(length_m=length_h, peak_c=peak_h, hbm_link_mm=hbm_link_mm(problem, hand),
                             gpu_peak_c=max(t for n, t in die_h.items() if n.startswith('GPU')),
                             hbm_peak_c=max(t for n, t in die_h.items() if n.startswith('HBM'))),
                   top_h_w_m2k=case['top_h_w_m2k'], front_size=len(points),
                   shortest_over_hand=float(front.length_m.min()/length_h), **outcome(points, (length_h, peak_h)))
        for ratio in (1.0, 1.1, 1.25):
            inside = np.flatnonzero(front.length_m <= ratio*length_h)
            if len(inside):
                i = int(inside[np.argmin(front.peak_c[inside])])
                die = front.summary['front'][i]['die_peak_c']
                row[f'coolest_within_{ratio:g}x'] = dict(
                    length_m=float(front.length_m[i]), peak_c=float(front.peak_c[i]), hbm_link_mm=hbm_link_mm(problem, front.layouts[i]),
                    gpu_peak_c=max(t for n, t in die.items() if n.startswith('GPU')),
                    hbm_peak_c=max(t for n, t in die.items() if n.startswith('HBM')))
        out[case['name']] = row
        print(case['name'], row['outcome'], 'dT', row['d_t_k'] and round(row['d_t_k'], 2), 'dL', row['d_l'] and round(row['d_l'], 3),
              'hand', round(length_h, 3), round(peak_h, 2), flush=True)
    args.output.write_text(json.dumps(dict(plan='docs/industrial-cases-plan.md', physical_qualified=False, cases=out),
                                      indent=1) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('build', 'assess'))
    p.add_argument('--cases', type=Path, help='assess: directory written by build')
    p.add_argument('--runs', type=Path, help='assess: run_reference_front outputs, one directory per case name')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    {'build': build, 'assess': assess}[args.command](args)


if __name__ == '__main__':
    main()
