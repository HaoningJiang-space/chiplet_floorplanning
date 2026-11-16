"""Which die limits an H100-class package in prefill vs decode (plan: docs/phase-power-plan.md).

The hand layout (GPU in the middle, three HBM3 stacks on each side, one of them a dummy) is solved with the
measured per-phase power split; the sink-top convection is calibrated so that the GPU peak in prefill equals a
target temperature. Each die's overshoot over its own limit decides which die binds.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, is_legal, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import die_peaks_c

GAP_UM = 200.0                       # IHP Open-ADK ASM.b
GPU_UM, HBM_UM = (26000.0, 31300.0), (11000.0, 11000.0)
CARRIER_UM = (50000.0, 48000.0)
NAMES = ('GPU', 'HBM_L0', 'HBM_L1', 'HBM_L2', 'HBM_R0', 'HBM_R1', 'HBM_DUMMY')
# Measured centre values (docs/industrial-benchmark-data.md): GPU die W, each working HBM stack W.
PHASES = dict(prefill=(540.0, 22.0), decode=(240.0, 16.0), idle=(60.0, 13.0))
LIMITS = dict(gpu=(95.0, 105.0), hbm=(85.0, 95.0))      # first value is the primary setting
CALIBRATION_C = (85.0, 75.0, 95.0)                       # first value is the primary setting
RESOLUTION = 64


def h100_problem(phase):
    gpu, hbm = PHASES[phase]
    power = np.array([gpu] + [hbm]*5 + [0.0])
    size = np.array([GPU_UM] + [HBM_UM]*6)
    return Problem('h100_class', NAMES, size, power, CARRIER_UM, np.zeros((0, 2), int), np.zeros((0, 2, 2)))


def hand_layout():
    cx, cy = CARRIER_UM[0]/2, CARRIER_UM[1]/2
    side = GPU_UM[0]/2 + GAP_UM + HBM_UM[0]/2
    rows = [cy - HBM_UM[1] - GAP_UM, cy, cy + HBM_UM[1] + GAP_UM]
    centre = [(cx, cy)] + [(cx - side, y) for y in rows] + [(cx + side, y) for y in rows[::-1]]
    return Layout(np.array(centre), np.zeros(7, int))


def die_temperatures(problem, layout, top_h):
    _, rise, edges = solve(thermal_case_data(problem, layout, GAP_UM, RESOLUTION, top_h_w_m2k=top_h))
    return die_peaks_c(problem, layout, rise, edges)


def calibrate_h(layout, target_c, low=50.0, high=1e6, iterations=60):
    """Sink-top h (W/m^2K) at which the GPU peak in prefill equals target_c (bisection in log h)."""
    problem = h100_problem('prefill')
    for _ in range(iterations):
        mid = np.sqrt(low*high)
        if die_temperatures(problem, layout, mid)[0] > target_c:
            low = mid
        else:
            high = mid
    return float(np.sqrt(low*high))


def binding(temps, gpu_limit, hbm_limit):
    """(die index with the largest overshoot, overshoot K per die); the dummy (no power) is excluded."""
    limits = np.array([gpu_limit] + [hbm_limit]*6)
    over = temps - limits
    over[-1] = -np.inf
    return int(np.argmax(over)), over


def analyse():
    layout = hand_layout()
    assert is_legal(h100_problem('prefill'), layout, GAP_UM)
    out = dict(plan='docs/phase-power-plan.md', physical_qualified=False, calibrations={})
    for target in CALIBRATION_C:
        h = calibrate_h(layout, target)
        temps = {phase: die_temperatures(h100_problem(phase), layout, h) for phase in PHASES}
        rows = {}
        for g in LIMITS['gpu']:
            for m in LIMITS['hbm']:
                verdicts = {}
                for phase, t in temps.items():
                    k, over = binding(t, g, m)
                    verdicts[phase] = dict(binding=NAMES[k], overshoot_k=float(over[k]),
                                           gpu_overshoot_k=float(over[0]), hbm_overshoot_k=float(over[1:-1].max()))
                verdicts['switch'] = verdicts['prefill']['binding'][:3] != verdicts['decode']['binding'][:3]
                rows[f'gpu{g:g}_hbm{m:g}'] = verdicts
        out['calibrations'][f'{target:g}'] = dict(top_h_w_m2k=h, temps_c={p: dict(zip(NAMES, map(float, t)))
                                                                          for p, t in temps.items()}, limits=rows)
        print(f'T_cal {target:g} C: h {h:.0f} W/m2K', {p: (round(t[0], 1), round(t[1:-1].max(), 1)) for p, t in temps.items()},
              {k: v['switch'] for k, v in rows.items()}, flush=True)
    primary = out['calibrations'][f'{CALIBRATION_C[0]:g}']['limits'][f'gpu{LIMITS["gpu"][0]:g}_hbm{LIMITS["hbm"][0]:g}']
    switches = sum(v['switch'] for c in out['calibrations'].values() for v in c['limits'].values())
    out['verdict'] = ('switch' if primary['switch'] else
                      'no_switch' if switches <= 2 else 'uncertain')
    out['switching_settings'] = switches
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    out = analyse()
    args.output.write_text(json.dumps(out, indent=1) + '\n')
    print(out['verdict'], out['switching_settings'])


if __name__ == '__main__':
    main()
