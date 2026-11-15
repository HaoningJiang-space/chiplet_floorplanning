"""True regret of the nominal-best layout under a workload, by searching each power map directly
(plan: docs/coupling-search-plan.md).

For each target (case, scenario): lp_epsilon with the same start set, budget and length cap
(1.25 x the nominal front's shortest length) under the nominal and under the scenario power map.
N = coolest nominal layout within the cap (nominal front and nominal search); S = coolest scenario
layout within the cap (nominal front, N and scenario search, all under the scenario map).
regret = T_s(N) - T_s(S); reverse cost = T_nom(S) - T_nom(N).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np

from chiplet_floorplanning.placement import (Evaluator, Layout, Problem, pin_manhattan_um, sample_legal, solve_peak,
                                             thermal_case_data)
from chiplet_floorplanning.placement.methods import METHODS, Run
from chiplet_floorplanning.placement.search import length_descent
from workload_leverage import budget_power, is_compute, kind, scenarios

SEED, FV_SOLVES, BATCH, STARTS = 2026111401, 1000, 48, 48
CAP_FACTOR, MEANINGFUL_K = 1.25, 1.0
# Whole-accelerator power as a share of TDP: prefill ~0.9 (H100, NVML; RPU, arXiv 2602.18568),
# decode 0.5-0.6 (A100/H100; xPU-athalon, arXiv 2604.10852). Memory activity is declared, not measured.
LLM = dict(prefill=dict(total=.9, memory=.5), decode_hbm_full=dict(total=.55, memory=1.),
           decode_hbm_half=dict(total=.55, memory=.5))
DECLARED = [(10, 'cpu_idle'), (10, 'compute_half'), (3, 'even_idle'), (9, 'gpu_idle'), (4, 'even_idle')]
CONTROLS = [(5, 'even_idle'), (6, 'gpu_idle')]
LLM_CASES = (1, 2, 4, 6, 9)


def llm_power(names, nominal, total, memory):
    """Memory at the declared activity, others nominal, all compute dies at one activity in [0.2, 1]
    chosen so the package power is `total` x nominal (clipped when the bounds bind)."""
    compute = is_compute(names)
    mem = np.array([kind(n).startswith(('HBM', 'DRAM')) for n in names])
    power = np.where(mem, memory*nominal, nominal)
    x = (total*nominal.sum() - power[~compute].sum())/nominal[compute].sum()
    return np.where(compute, np.clip(x, .2, 1.)*nominal, power), float(np.clip(x, .2, 1.))


def targets(names, case):
    nominal_kinds = scenarios(names)
    out = {}
    for c, s in DECLARED + CONTROLS:
        if c == case:
            out[f'budget/{s}'] = ('control' if (c, s) in CONTROLS else 'declared', s)
    if case in LLM_CASES:
        for s in LLM:
            out[f'llm/{s}'] = ('llm', s)
    if any(v[0] != 'llm' and v[1] not in nominal_kinds for v in out.values()):
        raise SystemExit(f'case {case}: declared scenario not applicable')
    return out


def peak(job):
    case_path, power, centre, rotation, gap_um, resolution = job
    problem = replace(Problem.from_imported(json.loads(Path(case_path).read_text())), power_w=np.asarray(power))
    return solve_peak(thermal_case_data(problem, Layout(centre, rotation), gap_um, resolution))['peak_power_layer_c']


def search(problem, power, cap, initial, gap_um, resolution, workers):
    problem = replace(problem, power_w=power)
    with Evaluator(problem, gap_um, resolution, workers) as evaluator:
        run = Run(evaluator, FV_SOLVES)
        METHODS['lp_epsilon'](run, initial, np.random.default_rng([SEED, 10]), batch=BATCH, length_caps_m=[cap])
    length, peaks, _ = run.arrays()
    return run.layouts, length, peaks, evaluator.solves, run.stop_reason


def analyse(case, case_path, summary_path, layouts_path, workers):
    summary = json.loads(Path(summary_path).read_text())
    if sha256(Path(case_path).read_bytes()).hexdigest() != summary['case_sha256']:
        raise SystemExit(f'{case_path} is not the case the front was frozen on')
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    gap, res = summary['gap_um'], summary['fv_resolution']
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    front = [Layout(z['centre_um'][i], z['rotation_deg'][i]) for i in index]
    f_length = np.array([p['length_m'] for p in summary['front']])
    f_peak = np.array([p['peak_c'] for p in summary['front']])
    # Review of 56f3af6: the summary's numbers must describe these coordinates, not another layout file.
    actual = np.array([pin_manhattan_um(problem, l).sum()/1e6 for l in front])
    if np.abs(actual - f_length).max() > 1e-9:
        raise SystemExit('front lengths do not match the layout coordinates')
    cap = CAP_FACTOR*f_length.min()
    rng = np.random.default_rng(SEED)
    initial = [sample_legal(problem, gap, rng) for _ in range(STARTS)]
    initial += [length_descent(problem, sample_legal(problem, gap, rng), rng, gap) for _ in range(STARTS)]

    def solve_all(power, layouts):
        jobs = [(str(case_path), power, l.centre_um, l.rotation_deg, gap, res) for l in layouts]
        with ProcessPoolExecutor(workers) as pool:
            return np.array(list(pool.map(peak, jobs, chunksize=4)))

    nominal = problem.power_w
    if np.abs(solve_all(nominal, front) - f_peak).max() > 1e-6:
        raise SystemExit('front peaks do not match the layout coordinates')
    started = time.perf_counter()
    n_layouts, n_length, n_peak, n_solves, n_stop = search(problem, nominal, cap, initial, gap, res, workers)
    pool_l = front + n_layouts
    pool_len, pool_peak = np.r_[f_length, n_length], np.r_[f_peak, n_peak]
    ok = np.flatnonzero(pool_len <= cap + 1e-12)
    n_best = int(ok[np.argmin(pool_peak[ok])])
    nominal_best = pool_l[n_best]
    out = dict(case=summary['case'], cap_m=cap, nominal=dict(
        solves=n_solves, stop=n_stop, best_from='front' if n_best < len(front) else 'search',
        best_length_m=float(pool_len[n_best]), best_peak_c=float(pool_peak[n_best]),
        front_best_peak_c=float(f_peak[f_length <= cap + 1e-12].min())), targets={})
    for name, (group, s) in targets(problem.names, case).items():
        if group == 'llm':
            power, x = llm_power(problem.names, nominal, **LLM[s])
        else:
            power, x = budget_power(nominal, scenarios(problem.names)[s], is_compute(problem.names)), None
        s_layouts, s_length, s_peak, s_solves, s_stop = search(problem, power, cap, initial, gap, res, workers)
        cand = front + [nominal_best] + s_layouts
        cand_len = np.r_[f_length, pool_len[n_best], s_length]
        cand_peak = np.r_[solve_all(power, front + [nominal_best]), s_peak]
        ok = np.flatnonzero(cand_len <= cap + 1e-12)
        b = int(ok[np.argmin(cand_peak[ok])])
        t_s_n, t_s_s = float(cand_peak[len(front)]), float(cand_peak[b])
        t_nom_s = float(solve_all(nominal, [cand[b]])[0])
        out['targets'][name] = dict(
            group=group, power_w=power.tolist(), package_w=float(power.sum()), compute_activity=x,
            solves=s_solves, stop=s_stop, regret_k=t_s_n - t_s_s, reverse_cost_k=t_nom_s - float(pool_peak[n_best]),
            scenario_best_from='front' if b < len(front) else 'nominal_best' if b == len(front) else 'search',
            scenario_best_length_m=float(cand_len[b]), nominal_best_under_scenario_c=t_s_n,
            scenario_best_c=t_s_s, centre_um=cand[b].centre_um.tolist(), rotation_deg=cand[b].rotation_deg.tolist())
        print(summary['case'], name, f"regret {t_s_n - t_s_s:.2f} K reverse {out['targets'][name]['reverse_cost_k']:.2f} K",
              f"{time.perf_counter() - started:.0f}s", flush=True)
    out['nominal'].update(centre_um=nominal_best.centre_um.tolist(), rotation_deg=nominal_best.rotation_deg.tolist())
    return out


def verdict(cases, group):
    hit = sum(t['regret_k'] >= MEANINGFUL_K for c in cases for t in c['targets'].values() if t['group'] == group)
    return 'worthwhile' if hit >= 3 else 'uncertain' if hit else 'not_found'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=int, nargs='+', default=[1, 2, 3, 4, 5, 6, 9, 10])
    parser.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    parser.add_argument('--front-dir', type=Path, default=Path('results/front-gap0'))
    parser.add_argument('--summary-dir', type=Path, default=Path('docs/evidence/front-gap0'))
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    cases = [analyse(n, args.import_dir/f'Case{n}.json', args.summary_dir/f'case{n}-summary.json',
                     args.front_dir/f'case{n}'/'layouts.npz', args.workers) for n in args.cases]
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, plan='docs/coupling-search-plan.md',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), seed=SEED, fv_solves=FV_SOLVES,
        cap_factor=CAP_FACTOR, meaningful_k=MEANINGFUL_K, llm=LLM,
        verdict={g: verdict(cases, g) for g in ('declared', 'llm')}, cases=cases), indent=1) + '\n')


if __name__ == '__main__':
    main()
