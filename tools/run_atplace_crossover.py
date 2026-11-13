"""Freeze and run one local crossover ablation against the reviewed v1 B record."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from atplace_crossover import METHOD, run_policy
from atplace_pin_geometry import make_thermal_case
from run_atplace_search import (SOURCES as V1_SOURCES, check_plan as check_v1, digest,
                               object_hash, raw, verify_record, write_new)
from chiplet_floorplanning.model import parse_case
from solve_tap_fv_hits import run

BASE_COMMIT = '543416548bf43970d12db1b143a56768d5d42aa0'
BASE_PLAN = 'docs/evidence/atplace-case1-search-plan-v1.json'
BASE_EVIDENCE = 'docs/evidence/atplace-case1-search-v1.json'
SOURCES = (*V1_SOURCES, 'tools/atplace_crossover.py', 'tools/run_atplace_crossover.py',
           'docs/atplace-case1-crossover-protocol.md')
PROTOCOL = 'atplace-case1-compatible-crossover-v1'


def design_signature(data):
    """Everything except whole-die poses must stay fixed, including the mesh rule."""
    d = deepcopy(data)
    for c in d['chiplets']:
        del c['placement_mm']
        del c['rotation_deg']
    return object_hash(d)


def thermal_admitted(t, power_w, boundary_mean_c):
    return bool(t['numerical_admission_passed'] and t['hits_receipt']['accepted']
                and abs(t['source_power_w']-power_w) < 1e-8
                and abs(t['mapped_power_w']-power_w) < 1e-8
                and abs(t['energy_balance_error_w']) <= 1e-4
                and t['original_relative_residual'] <= 1e-8 and t['max_reference_difference_k'] <= 1e-3
                and t['min_rise_k'] >= -1e-8 and t['peak_power_layer_c'] >= boundary_mean_c
                and t['max_internal_coefficient_change_w_k'] == 0
                and t['max_asymmetry_w_k'] == 0 and t['max_offdiagonal_w_k'] <= 0)


def frozen_hashes():
    return {p: digest(raw(p)) for p in SOURCES}


def freeze(input_path, plan_path):
    source, old = check_v1(input_path, BASE_PLAN)
    for path in (BASE_PLAN, BASE_EVIDENCE):
        committed = subprocess.check_output(['git', 'show', BASE_COMMIT+':'+path]).replace(b'\r\n', b'\n')
        if committed != raw(path):
            raise ValueError('Baseline file differs from the independently reviewed commit')
    prior = json.loads(raw(BASE_EVIDENCE))
    if prior['status'] != 'verified_single_seed_comparison' or prior['plan'] != old:
        raise ValueError('Reviewed baseline plan mismatch')
    baseline = next(r for r in prior['records'] if r['method'] == 'nsga2_pin_guided')
    if (baseline['plan_sha256'] != digest(raw(BASE_PLAN))
            or baseline['input_sha256'] != old['imported_sha256']
            or baseline['status'] != 'complete_thermal_budget'):
        raise ValueError('Baseline provenance or completion mismatch')
    verify_record(source, old, baseline)  # Saved-response replay only, no new heat solves.
    plan = deepcopy(old)
    plan.update(protocol=PROTOCOL, methods=['nsga2_pin_guided', METHOD],
                code_base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                source_sha256=frozen_hashes(),
                baseline=dict(commit=BASE_COMMIT, path=BASE_EVIDENCE, sha256=digest(raw(BASE_EVIDENCE)),
                              plan_path=BASE_PLAN, plan_sha256=digest(raw(BASE_PLAN)),
                              method='nsga2_pin_guided', admission='reviewed plus local saved-response replay'))
    data = make_thermal_case(source, plan['initialization']['placements'][0], plan['gap_um'])
    power = sum(float(c['power_w_decimal']) for c in source['chiplets'])
    rect = data['thermal']['layers'][-1]['rect_mm']
    area = rect['width']*rect['height']/1e6
    h = data['thermal']['top_h_w_m2k']
    plan['physical_scenario'] = dict(design_sha256=design_signature(data), source_power_w=power,
        ambient_c=data['thermal']['ambient_c'], top_area_m2=area, top_h_w_m2k=h,
        boundary_surface_mean_c_from_global_balance=data['thermal']['ambient_c']+power/(h*area),
        scope='constant source powers/materials/boundaries; only rigid chip poses vary; no measured package or routed RC')
    write_new(plan_path, plan)
    print(json.dumps(dict(protocol=PROTOCOL, plan_sha256=digest(raw(plan_path)),
                         baseline_replay=True, new_thermal_queries=0)))


def check_plan(input_path, plan_path):
    plan = json.loads(raw(plan_path))
    if (plan['protocol'] != PROTOCOL or plan['source_sha256'] != frozen_hashes()
            or digest(raw(input_path)) != plan['imported_sha256']):
        raise ValueError('Frozen input or implementation mismatch')
    b = plan['baseline']
    if digest(raw(b['path'])) != b['sha256'] or digest(raw(b['plan_path'])) != b['plan_sha256']:
        raise ValueError('Reviewed baseline changed after freeze')
    check_v1(input_path, b['plan_path'])
    baseline = next(r for r in json.loads(raw(b['path']))['records'] if r['method'] == b['method'])
    return json.loads(raw(input_path)), plan, baseline


def execute(input_path, plan_path, hits, output):
    source, plan, _ = check_plan(input_path, plan_path)
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip()
    if sha != plan['hits_commit'] or dirty:
        raise ValueError('Expected clean pinned HiTS source')
    output.mkdir(parents=True, exist_ok=False)
    queries = 0
    def solve(data):
        nonlocal queries
        physical = plan['physical_scenario']
        if design_signature(data) != physical['design_sha256']:
            raise ValueError('A layout changed dimensions, power, ports, material, mesh policy or boundaries')
        q = queries
        queries += 1
        summary, _, _, _ = run(parse_case(data), hits)
        summary.update(evaluated_case_sha256=object_hash(data), design_sha256=design_signature(data),
                       scope='unchanged Case1 steady uniform FV model; no routed RC or timing')
        summary['scenario_admission_passed'] = thermal_admitted(summary, physical['source_power_w'],
            physical['boundary_surface_mean_c_from_global_balance'])
        write_new(output/f'query-{q:03d}.json', summary)
        if not summary['scenario_admission_passed']:
            raise ValueError('Declared physical/numerical scenario check failed')
        print(METHOD, q+1, summary['peak_power_layer_c'], flush=True)
        return summary
    record = run_policy(source, plan, solve)
    record.update(plan_sha256=digest(raw(plan_path)), input_sha256=plan['imported_sha256'], hits_commit=sha)
    write_new(output/'result.json', record)
    print(record['status'], record['reason'], json.dumps(record['effort']), flush=True)
    if record['status'] == 'failed_unknown':
        raise SystemExit('failed_unknown: '+str(record['reason']))


def verify_candidate(source, plan, record):
    if record['method'] != METHOD or record['status'] not in ('complete_thermal_budget', 'capped'):
        raise ValueError('Unexpected method or failed/unknown candidate')
    for key, cap in (('proposals', 'proposal_cap'), ('pin_calls', 'pin_call_cap'),
                     ('candidate_checks', 'candidate_check_cap'), ('thermal_queries', 'thermal_budget')):
        if record['effort'][key] > plan[cap]:
            raise ValueError('Candidate cost cap exceeded')
    if record['status'] == 'complete_thermal_budget' and record['effort']['thermal_queries'] != plan['thermal_budget']:
        raise ValueError('Incorrect completion status')
    physical = plan['physical_scenario']
    for q in record['thermal_records']:
        t = q['thermal']
        if (t['design_sha256'] != physical['design_sha256'] or not t['scenario_admission_passed']
                or not thermal_admitted(t, physical['source_power_w'], physical['boundary_surface_mean_c_from_global_balance'])):
            raise ValueError('Physical scenario receipt mismatch')
    index = 0
    def replay_solve(data):
        nonlocal index
        t = record['thermal_records'][index]['thermal']
        index += 1
        if object_hash(data) != t['evaluated_case_sha256'] or design_signature(data) != t['design_sha256']:
            raise ValueError('Replay requested a different physical input')
        return deepcopy(t)
    replay = run_policy(source, plan, replay_solve)
    for key in ('status', 'reason', 'rows', 'events', 'physical_comparison', 'checkpoints',
                'pareto_row_indices', 'complete_generations', 'final_generation_offspring', 'generation_records'):
        if replay[key] != record[key]:
            raise ValueError('Policy replay mismatch: '+key)
    for key, value in record['effort'].items():
        if not key.endswith('_seconds') and replay['effort'][key] != value:
            raise ValueError('Effort replay mismatch: '+key)
    if index != len(record['thermal_records']):
        raise ValueError('Unconsumed thermal records')


def report(input_path, plan_path, result_path, output):
    source, plan, baseline = check_plan(input_path, plan_path)
    candidate = json.loads(raw(result_path))
    if (candidate['plan_sha256'] != digest(raw(plan_path)) or candidate['input_sha256'] != plan['imported_sha256']
            or candidate['hits_commit'] != plan['hits_commit']):
        raise ValueError('Candidate provenance mismatch')
    verify_candidate(source, plan, candidate)
    n = plan['population']
    if candidate['rows'][:n] != baseline['rows'][:n]:
        raise ValueError('Historical baseline does not share identical initial joint rows')
    pairs = {}
    for axis, field in (('temperature_at_length', 'peak_c'), ('length_at_temperature', 'pin_length_m')):
        a, b = [r['physical_comparison'][axis]['selected'] for r in (baseline, candidate)]
        gain = a[field]-b[field] if a and b else None
        pairs[axis] = dict(baseline=a, candidate=b, gain=gain, unit='K' if field == 'peak_c' else 'm',
                           status='both_attained' if a and b else 'incomplete_attainment')
        if field == 'pin_length_m':
            pairs[axis]['reduction_percent'] = 100*gain/a[field] if gain is not None and a[field] > 0 else None
    result = dict(status='verified_single_seed_crossover_comparison', plan=plan, plan_sha256=digest(raw(plan_path)),
                  baseline_reused=True, candidate_policy_replay=True,
                  source_result=dict(path=str(result_path), sha256=digest(raw(result_path))),
                  paired_comparison=pairs, records=[baseline, candidate],
                  independent_physical_calibration=False, timing_closed=False,
                  interpretation='one frozen Case1 seed; crossover-only intervention; costs and joint outcomes, not stable superiority')
    write_new(output, result)
    print(json.dumps({k: dict(gain=v['gain'], unit=v['unit'], reduction_percent=v.get('reduction_percent'))
                      for k, v in pairs.items()}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--freeze', action='store_true')
    p.add_argument('--hits', type=Path)
    p.add_argument('--report', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.freeze:
        freeze(a.input, a.plan)
    elif a.report and a.output:
        report(a.input, a.plan, a.report, a.output)
    elif a.hits and a.output:
        execute(a.input, a.plan, a.hits, a.output)
    else:
        p.error('Choose freeze, hits/output, or report/output')


if __name__ == '__main__':
    main()
