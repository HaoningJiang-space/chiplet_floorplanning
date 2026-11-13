"""Freeze, execute locally, and verify the Case1 single-seed screening ablation."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from atplace_pin_geometry import pin_objective
from atplace_search import initialize, identities, profile, run_policy
from chiplet_floorplanning.model import parse_case
from solve_tap_fv_hits import run

HITS_COMMIT = 'be59924de3f0c1a3d6d134aea411d1264cfa64c6'
SOURCES = ('tools/atplace_search.py', 'tools/run_atplace_search.py',
           'tools/atplace_pin_geometry.py', 'tools/import_atplace_cases.py',
           'tools/solve_tap_fv_hits.py', 'src/chiplet_floorplanning/model.py',
           'src/chiplet_floorplanning/package.py', 'src/chiplet_floorplanning/power.py',
           'src/chiplet_floorplanning/mesh.py', 'docs/atplace-case1-search-protocol.md')


def raw(path):
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def object_hash(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def hashes():
    return {p: digest(raw(p)) for p in SOURCES}


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def freeze(input_path, plan_path):
    source = json.loads(raw(input_path))
    imported = json.loads(raw('docs/evidence/atplace-import.json'))
    expected = next(x for x in imported['cases'] if x['case'] == 'Case1')
    if source['name'] != 'Case1' or digest(raw(input_path)) != expected['imported_sha256']:
        raise ValueError('Expected the verified unchanged Case1 import')
    accepted_raw = raw('docs/evidence/atplace-case1-acceptance.json')
    accepted = json.loads(accepted_raw)
    base = accepted['records'][0]
    plan = dict(protocol='atplace-case1-screening-v1', seed=2026111200, population=16,
                grid_um=1000, gap_um=1000, thermal_budget=48, post_initial_thermal_budget=32,
                proposal_cap=512, pin_call_cap=2048, candidate_check_cap=2000000,
                methods=['nsga2_legal', 'nsga2_pin_guided'],
                length_cap_m=base['metric']['total_pin_manhattan_m'],
                temperature_cap_c=base['thermal']['peak_power_layer_c'],
                imported_sha256=digest(raw(input_path)), accepted_evidence_sha256=digest(accepted_raw),
                source_commit=source['source_commit'], hits_commit=HITS_COMMIT,
                code_base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                source_sha256=hashes())
    plan['initialization'] = initialize(source, base['placements'], plan)
    write_new(plan_path, plan)
    print(json.dumps(dict(seed=plan['seed'], initial_layouts=len(plan['initialization']['placements']),
                         initial_candidate_checks=plan['initialization']['candidate_checks'],
                         construction_attempts=plan['initialization']['construction_attempts'],
                         plan_sha256=digest(raw(plan_path)))))


def check_plan(input_path, plan_path):
    plan = json.loads(raw(plan_path))
    if plan['protocol'] != 'atplace-case1-screening-v1' or hashes() != plan['source_sha256']:
        raise ValueError('Frozen implementation/protocol mismatch')
    if digest(raw(input_path)) != plan['imported_sha256']:
        raise ValueError('Frozen source input mismatch')
    return json.loads(raw(input_path)), plan


def execute(input_path, plan_path, method, hits, output):
    source, plan = check_plan(input_path, plan_path)
    if method not in plan['methods']:
        raise ValueError('Method is not frozen')
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip()
    if sha != plan['hits_commit'] or dirty:
        raise ValueError('Expected clean pinned HiTS source')
    output.mkdir(parents=True, exist_ok=False)
    attempted = 0
    def solve(data):
        nonlocal attempted
        query = attempted
        attempted += 1
        summary, _, _, _ = run(parse_case(data), hits)
        summary['evaluated_case_sha256'] = object_hash(data)
        summary['scope'] = 'declared Case1 common FV model; no routed RC or timing'
        write_new(output/f'query-{query:03d}.json', summary)
        print(method, query+1, summary['peak_power_layer_c'], flush=True)
        return summary
    result = run_policy(source, plan, method, solve)
    result.update(plan_sha256=digest(raw(plan_path)), input_sha256=plan['imported_sha256'],
                  code_base_commit=plan['code_base_commit'], hits_commit=sha)
    write_new(output/'result.json', result)
    print(result['status'], result['reason'], json.dumps(result['effort']), flush=True)
    if result['status'] == 'failed_unknown':
        raise SystemExit('failed_unknown: '+str(result['reason']))


def verify_record(source, plan, record):
    if record['status'] not in ('complete_thermal_budget', 'capped'):
        raise ValueError('Failed/unknown run cannot become a completed comparison')
    effort = record['effort']
    for key, cap in (('proposals', 'proposal_cap'), ('pin_calls', 'pin_call_cap'),
                     ('candidate_checks', 'candidate_check_cap'), ('thermal_queries', 'thermal_budget')):
        if effort[key] > plan[cap]:
            raise ValueError('Cost cap exceeded')
    if record['status'] == 'complete_thermal_budget' and effort['thermal_queries'] != plan['thermal_budget']:
        raise ValueError('Incorrect completion status')
    thermal_keys, full_keys = {}, set()
    for row in record['rows']:
        full, thermal = identities(source, row['placement'], plan['gap_um'])
        if full in full_keys or row['layout_key'] != [list(x) for x in full] or row['thermal_key'] != [list(x) for x in thermal]:
            raise ValueError('Layout identity mismatch')
        full_keys.add(full)
        if thermal in thermal_keys:
            if not row['thermal_cache_hit'] or row['thermal_solve_id'] != thermal_keys[thermal]:
                raise ValueError('Incorrect cache reference')
        else:
            if row['thermal_cache_hit'] or row['thermal_solve_id'] != len(thermal_keys):
                raise ValueError('Incorrect fresh solve identity')
            thermal_keys[thermal] = row['thermal_solve_id']
        t = record['thermal_records'][row['thermal_solve_id']]['thermal']
        m = pin_objective(source, row['placement'], plan['gap_um'])
        if row['peak_c'] != t['peak_power_layer_c'] or row['pin_length_m'] != m['total_pin_manhattan_m']:
            raise ValueError('Joint metric differs from its actual layout')
        if row['pin_length_um_decimal'] != m['total_pin_manhattan_um_decimal']:
            raise ValueError('Exact pin total mismatch')
    expected_power = sum(float(c['power_w_decimal']) for c in source['chiplets'])
    for q in record['thermal_records']:
        t = q['thermal']
        if not (t['numerical_admission_passed'] and t['hits_receipt']['accepted']
                and abs(t['source_power_w']-expected_power) < 1e-8
                and abs(t['energy_balance_error_w']) <= 1e-4
                and t['original_relative_residual'] <= 1e-8 and t['max_reference_difference_k'] <= 1e-3
                and t['min_rise_k'] >= -1e-8 and t['max_internal_coefficient_change_w_k'] == 0
                and t['max_asymmetry_w_k'] == 0 and t['max_offdiagonal_w_k'] <= 0):
            raise ValueError('Numerical admission mismatch')
    index = 0
    def replay_solve(data):
        nonlocal index
        t = record['thermal_records'][index]['thermal']
        index += 1
        if object_hash(data) != t['evaluated_case_sha256']:
            raise ValueError('Replay requested different physical input')
        return deepcopy(t)
    replay = run_policy(source, plan, record['method'], replay_solve)
    for key in ('status', 'reason', 'rows', 'events', 'physical_comparison', 'checkpoints',
                'pareto_row_indices', 'complete_generations', 'final_generation_offspring'):
        if replay[key] != record[key]:
            raise ValueError('Policy replay mismatch: '+key)
    for key, value in effort.items():
        if not key.endswith('_seconds') and replay['effort'][key] != value:
            raise ValueError('Cost replay mismatch: '+key)
    if index != len(record['thermal_records']):
        raise ValueError('Replay did not consume every thermal query')
    return True


def report(input_path, plan_path, paths, output):
    source, plan = check_plan(input_path, plan_path)
    records = [json.loads(raw(p)) for p in paths]
    if [r['method'] for r in records] != plan['methods']:
        raise ValueError('Expected exactly the two frozen methods in A/B order')
    for r in records:
        if r['plan_sha256'] != digest(raw(plan_path)) or r['input_sha256'] != plan['imported_sha256']:
            raise ValueError('Record provenance mismatch')
        verify_record(source, plan, r)
    # Both methods paid for exactly the same 16 full initial layouts.
    if records[0]['rows'][:16] != records[1]['rows'][:16]:
        raise ValueError('Paired initial layout/objective records differ')
    a, b = [r['physical_comparison'] for r in records]
    pairs = {}
    for axis, field in (('temperature_at_length', 'peak_c'), ('length_at_temperature', 'pin_length_m')):
        ar, br = a[axis]['selected'], b[axis]['selected']
        gain = ar[field]-br[field] if ar and br else None
        pairs[axis] = dict(status='both_attained' if ar and br else 'candidate_only_attained' if br
                           else 'baseline_only_attained' if ar else 'neither_attained',
                           baseline=ar, candidate=br, gain=gain,
                           unit='K' if field == 'peak_c' else 'm')
        if field == 'pin_length_m':
            pairs[axis]['reduction_percent'] = 100*gain/ar[field] if gain is not None and ar[field] > 0 else None
    result = dict(status='verified_single_seed_comparison', plan_sha256=digest(raw(plan_path)),
                  plan=plan, source_results=[dict(path=str(p), sha256=digest(raw(p))) for p in paths],
                  policy_replay=True, independent_physical_calibration=False, timing_closed=False,
                  paired_comparison=pairs, records=records,
                  interpretation='one paired seed, declared-model screening ablation; no significance, SOTA or stable superiority claim')
    write_new(output, result)
    print(json.dumps(dict(status=result['status'], paired_comparison=pairs), indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--freeze', action='store_true')
    p.add_argument('--method', choices=['nsga2_legal', 'nsga2_pin_guided'])
    p.add_argument('--hits', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--report', type=Path, nargs=2)
    args = p.parse_args()
    if args.freeze:
        freeze(args.input, args.plan)
    elif args.report and args.output:
        report(args.input, args.plan, args.report, args.output)
    elif args.method and args.hits and args.output:
        execute(args.input, args.plan, args.method, args.hits, args.output)
    else:
        p.error('Choose freeze, method/hits/output, or report/output')


if __name__ == '__main__':
    main()
