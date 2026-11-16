"""ATPlace2.5D sweep for the head-to-head comparison (plan: docs/atplace-comparison-plan.md).

Runs on moe-server from the ATPlace_pub root with its own Python 3.9 env (Gurobi licence there). Per case: train the
thermal model once with the default parameters, place once in wirelength mode and five times in thermal mode with
the per-case default temp_weight_init scaled by MULTIPLIERS, then score every layout - and our exported layouts -
with ATSim. Output: <out>/<case>/<label>/{layout,summary,atsim}.json and <out>/<case>/timing.json.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

MULTIPLIERS = (0.01, 0.1, 1, 10, 100)


def last_json(text):
    """The last top-level JSON object printed by an ATPlace entry point."""
    decoder = json.JSONDecoder()
    for start in reversed([i for i, ch in enumerate(text) if ch == '{' and (i == 0 or text[i - 1] == '\n')]):
        try:
            return decoder.raw_decode(text[start:])[0]
        except ValueError:
            continue
    raise ValueError('no JSON summary in output')


def run(cmd, log):
    started = time.time()
    done = subprocess.run(cmd, capture_output=True, text=True)
    log.write_text(done.stdout + done.stderr)
    if done.returncode:
        raise RuntimeError(f'{cmd} failed, see {log}')
    return last_json(done.stdout), time.time() - started


def params(case, mode, threads, multiplier=None, sampling_s=None):
    """The case's own override file with thread counts (and a scaled thermal weight) set."""
    data = json.loads(Path(f'cases/{case}/{mode}.json').read_text())
    data.setdefault('opt', {})['num_threads'] = threads
    data.setdefault('thermal', {})['num_threads'] = threads
    if sampling_s is not None:   # only for the documented retry: ATPlace's default is 30 s
        data['thermal']['training_sampling_time_limit_s'] = sampling_s
    if multiplier is not None:
        data['thermal']['temp_weight_init'] = data['thermal']['temp_weight_init'] * multiplier
    return data


def sweep(case, out, threads, ours, sampling_s=None):
    py = sys.executable
    root = out / case
    root.mkdir(parents=True, exist_ok=True)
    timing = {}
    files = {}
    for label, mode, mult in [('wl', 'WL-driven', None)] + [(f'thermal_x{m:g}', 'Thermal-aware', m) for m in MULTIPLIERS]:
        path = root / f'{label}.params.json'
        path.write_text(json.dumps(params(case, mode, threads, mult, sampling_s), indent=1) + '\n')
        files[label] = path
    trained = True
    for label, path in files.items():
        mode = 'wl' if label == 'wl' else 'thermal'
        if mode == 'thermal' and 'train_s' not in timing and trained:
            # Wirelength mode needs no thermal model, so it runs (and is scored) even if training fails.
            try:
                _, timing['train_s'] = run([py, 'run_thermal_training.py', '--case', case, '--param_file',
                                            str(files['thermal_x1'])], root / 'train.log')
            except (RuntimeError, ValueError) as error:
                timing['train_failed'] = str(error)
                trained = False
        if mode == 'thermal' and not trained:
            continue
        try:
            summary, seconds = run([py, 'run_placement_opt.py', '--case', case, '--mode', mode, '--param_file', str(path)],
                                   root / f'{label}.log')
        except (RuntimeError, ValueError) as error:
            timing[label] = dict(failed=str(error))
            continue
        target = root / label
        target.mkdir(exist_ok=True)
        shutil.copy(summary['layout_json'], target / 'layout.json')
        (target / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
        timing[label] = dict(place_s=seconds, runtime_s=summary.get('runtime_s'), twl_m=summary.get('twl_m'))
    layouts = sorted(root.glob('*/layout.json'))
    if ours is not None:
        layouts += sorted((ours / case).glob('*.layout.json'))
    for layout in layouts:
        target = layout.parent / 'atsim.json' if layout.name == 'layout.json' else layout.with_name(
            layout.name.replace('.layout.json', '.atsim.json'))
        if target.exists():
            continue
        result, seconds = run([py, 'run_thermal_evaluation.py', '--layout', str(layout), '--param_file',
                               str(files['thermal_x1'])], target.with_suffix('.log'))
        result['eval_s'] = seconds
        target.write_text(json.dumps(result, indent=1) + '\n')
    (root / 'timing.json').write_text(json.dumps(timing, indent=1) + '\n')
    print(case, {k: v if not isinstance(v, dict) else v.get('twl_m') for k, v in timing.items()}, flush=True)
    return timing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', nargs='+', default=[f'Case{n}' for n in range(1, 11)])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ours', type=Path, help='exported layouts to score with ATSim: <ours>/<case>/kXXX.layout.json')
    p.add_argument('--threads', type=int, default=32)
    p.add_argument('--parallel', type=int, default=3)
    p.add_argument('--training-sampling-s', type=float, help='retry only: override the 30 s training sampler limit')
    args = p.parse_args()
    with ThreadPoolExecutor(args.parallel) as pool:
        list(pool.map(lambda c: sweep(c, args.out.resolve(), args.threads, args.ours and args.ours.resolve(),
                                      args.training_sampling_s), args.cases))


if __name__ == '__main__':
    main()
