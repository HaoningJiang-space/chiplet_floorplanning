"""Sequential local pilot; never overwrite or silently rerun an existing batch."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from build_tap_ihp_endpoints import source_bytes


def trial_order(plan):
    methods = tuple(plan.get('methods_to_run', ('random', 'sa', 'nsga2')))
    runs = []
    for index, seed in enumerate(plan['seeds']):
        order = methods[index % len(methods):] + methods[:index % len(methods)]
        for case in plan['cases']:
            for method in order:
                runs.append(dict(case=case['domain']['name'], method=method, seed=seed))
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--hits', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = source_bytes(args.plan)
    plan = json.loads(raw)
    runs = trial_order(plan)
    if plan['protocol'] != 'tap-online-r3-physical-v1' or len(runs) != 18 or plan['budget'] != 64:
        raise ValueError('Expected the frozen R3 18-new-run/64-query comparison')
    args.output.mkdir(parents=True, exist_ok=False)
    batch = dict(status='running', plan_sha256=hashlib.sha256(raw).hexdigest(),
                 commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                 order_rule='seed then workload; method order cyclically rotated per seed',
                 runs=runs, completed=[])
    def save():
        temporary = args.output/'batch.tmp'
        temporary.write_text(json.dumps(batch, indent=2)+'\n', encoding='utf-8')
        temporary.replace(args.output/'batch.json')
    save()
    for trial in runs:
        name = f"{trial['case']}-{trial['seed']}-{trial['method']}"
        directory = args.output/name
        with (args.output/f'{name}.log').open('w', encoding='utf-8') as log:
            child = subprocess.run([sys.executable, 'tools/run_tap_online.py', '--plan', str(args.plan),
                '--hits', str(args.hits), '--case', trial['case'], '--seed', str(trial['seed']),
                '--method', trial['method'], '--output', str(directory)], stdout=log, stderr=subprocess.STDOUT)
        path = directory/'result.json'
        result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        status = result.get('status', 'missing_result')
        batch['completed'].append(dict(**trial, status=status, exit_code=child.returncode,
                                        queries=result.get('queries'), reason=result.get('reason')))
        if status == 'complete_query_budget' and child.returncode == 0:
            pass
        elif status == 'stopped_at_limit':
            pass  # Preserve capped runs and continue the predeclared experiment.
        else:
            batch['status'] = 'failed_unknown'
            save()
            raise SystemExit(f'{name}: {status}; inspect saved log, do not silently restart')
        save()
        print(len(batch['completed']), '/', len(runs), name, status, flush=True)
    batch['status'] = 'complete_with_caps' if any(r['status'] == 'stopped_at_limit' for r in batch['completed']) else 'complete'
    save()


if __name__ == '__main__':
    main()
