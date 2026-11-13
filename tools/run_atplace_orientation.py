"""Freeze, run and replay a small B/D warm-start orientation-repair ablation."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from atplace_orientation_repair import candidate_pool, prepare, run_arm
from atplace_pin_geometry import make_thermal_case
from atplace_search import profile
from chiplet_floorplanning.model import parse_case
from run_atplace_crossover import design_signature, thermal_admitted
from run_atplace_routing_boundary import (INPUT, PLAN as PARENT_PLAN, HISTORIES,
                                          boundary_balance, check_plan as check_parent,
                                          nominal_response, read)
from run_atplace_search import digest, object_hash, raw, write_new
from solve_tap_fv_hits import run

PLAN = 'docs/evidence/atplace-case1-orientation-plan-v1.json'
PROTOCOL = 'atplace-case1-thermal-equivalent-orientation-v1'
ARMS = ('original_orientation', 'repaired_orientation')
SOURCES = ('tools/atplace_orientation_repair.py', 'tools/run_atplace_orientation.py',
           'docs/atplace-case1-orientation-protocol.md')


def source_hashes():
    return {p: digest(raw(p)) for p in SOURCES}


def prepare_pool(source, plan, repaired):
    return [prepare(source, c['placement'], plan, repaired) for c in plan['candidates']]


def warm_start(source, plan):
    rows, thermal, evidence = [], {}, []
    for anchor in plan['anchors']:
        record = read(HISTORIES[anchor['label']])['records'][-1]
        nominal, saved = nominal_response(source, plan, anchor['row'], record)
        if design_signature(nominal) != plan['design_sha256']:
            raise ValueError('Anchor design mismatch')
        response_id = 'warm/'+anchor['label']
        thermal[response_id] = deepcopy(saved)
        original = None
        for repaired in (False, True):
            entry = prepare(source, anchor['placement'], plan, repaired)
            if not entry['routing']['admitted']:
                raise ValueError('Common warm-start failed necessary routing')
            if not repaired:
                original = entry
                if entry['pin_length_m'] != anchor['row']['pin_length_m']:
                    raise ValueError('Original anchor pin objective mismatch')
            elif entry['thermal_key'] != original['thermal_key']:
                raise ValueError('Warm-start repair changed thermal identity')
            state = anchor['label']+('_repaired' if repaired else '_original')
            data = make_thermal_case(source, entry['placement'], plan['gap_um'], plan['resolution'])
            row = dict(row_index=len(rows), candidate_id=state, placement=entry['placement'],
                       layout_key=entry['layout_key'], thermal_key=entry['thermal_key'],
                       peak_c=saved['peak_power_layer_c'], pin_length_m=entry['pin_length_m'],
                       pin_length_um_decimal=entry['pin_length_um_decimal'],
                       thermal_response_id=response_id, thermal_cache_hit=True, thermal_queries_so_far=0,
                       layout_case_sha256=object_hash(data), response_case_sha256=saved['evaluated_case_sha256'])
            rows.append(row)
            evidence.append(dict(state=state, **entry))
    return rows, thermal, evidence


def preflight(source, plan):
    rows, _, evidence = warm_start(source, plan)
    pool = {arm: prepare_pool(source, plan, arm == ARMS[1]) for arm in ARMS}
    return dict(status='zero_heat_acceptance', new_thermal_queries=0,
                warm_rows=rows, warm_evidence=evidence,
                common_warm_pin_evaluations=sum(e['pin_evaluations'] for e in evidence),
                common_warm_physical_comparison=profile(rows, plan['length_cap_m'], plan['temperature_cap_c']),
                pool_by_anchor=dict(Counter(c['anchor'] for c in plan['candidates'])),
                arms={arm: dict(candidate_count=len(entries),
                               pin_evaluations=sum(e['pin_evaluations'] for e in entries),
                               length_feasible=sum(e['pin_length_m'] <= plan['length_cap_m'] for e in entries),
                               routing_admitted=sum(e['routing']['admitted'] for e in entries),
                               candidates=entries) for arm, entries in pool.items()})


def freeze(input_path, plan_path, output):
    source, parent = check_parent(input_path, PARENT_PLAN)
    anchors = [dict(label=f['label'], row=deepcopy(f['row']), placement=deepcopy(f['row']['placement']))
               for f in parent['finalists'] if f['label'] in ('B', 'D')]
    pool, attempts = candidate_pool(source, anchors, parent['gap_um'], 2000, parent['seed'])
    plan = dict(protocol=PROTOCOL, starting_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                input_path=str(input_path), input_sha256=digest(raw(input_path)),
                parent_plan_sha256=digest(raw(PARENT_PLAN)), sources_sha256=source_hashes(),
                seed=parent['seed'], gap_um=parent['gap_um'], grid_um=1000, step_um=2000,
                resolution=64, length_cap_m=parent['length_cap_m'], temperature_cap_c=parent['temperature_cap_c'],
                hits_commit=parent['hits_commit'], resources=deepcopy(parent['resources']),
                arms=list(ARMS), thermal_budget_per_arm=16, anchors=anchors,
                geometry_attempts=attempts, candidates=pool,
                design_sha256=design_signature(make_thermal_case(source, anchors[0]['placement'], parent['gap_um'])),
                comparison='B/D warm-start fixed local pool, not a cold-start optimizer ranking')
    receipt = preflight(source, plan)
    write_new(plan_path, plan)
    receipt['plan_sha256'] = digest(raw(plan_path))
    write_new(output, receipt)
    print(json.dumps(dict(plan_sha256=receipt['plan_sha256'], pool_by_anchor=receipt['pool_by_anchor'],
                         common_warm_pin_evaluations=receipt['common_warm_pin_evaluations'],
                         arms={a: {k: v for k, v in e.items() if k != 'candidates'} for a, e in receipt['arms'].items()},
                         warm_points=[(r['candidate_id'], r['peak_c'], r['pin_length_m']) for r in receipt['warm_rows']]), indent=2))


def check_plan(input_path, plan_path):
    source, _ = check_parent(input_path, PARENT_PLAN)
    plan = read(plan_path)
    if (plan['protocol'] != PROTOCOL or plan['input_sha256'] != digest(raw(input_path))
            or plan['parent_plan_sha256'] != digest(raw(PARENT_PLAN)) or plan['sources_sha256'] != source_hashes()):
        raise ValueError('Frozen protocol, input or implementation mismatch')
    pool, attempts = candidate_pool(source, plan['anchors'], plan['gap_um'], plan['step_um'], plan['seed'])
    if pool != plan['candidates'] or attempts != plan['geometry_attempts']:
        raise ValueError('Frozen candidate pool mismatch')
    return source, plan


def admitted_response(data, plan, response):
    balance = boundary_balance(data)
    if (design_signature(data) != plan['design_sha256']
            or not thermal_admitted(response, balance['power_w'], balance['surface_mean_c'])):
        raise ValueError('Physical design or numerical admission failed')


def execute(input_path, plan_path, hits, output):
    source, plan = check_plan(input_path, plan_path)
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != plan['hits_commit'] or subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Expected clean pinned HiTS')
    output.mkdir(parents=True, exist_ok=False)
    warm_rows, warm_thermal, warm_evidence = warm_start(source, plan)
    records = []
    for arm in ARMS:
        entries = prepare_pool(source, plan, arm == ARMS[1])
        query = 0
        def solve(data):
            nonlocal query
            response, _, _, _ = run(parse_case(data), hits)
            admitted_response(data, plan, response)
            response['evaluated_case_sha256'] = object_hash(data)
            write_new(output/f'{arm}-{query:02d}.json', dict(thermal=response, case_data=data))
            query += 1
            print(arm, query, response['peak_power_layer_c'], flush=True)
            return response
        record = run_arm(source, plan, arm, entries, warm_rows, warm_thermal, solve)
        records.append(record)
        write_new(output/(arm+'.json'), record)
    result = dict(status='completed_local_warm_start_ablation', plan_sha256=digest(raw(plan_path)),
                  execution_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  hits_commit=sha, seed=plan['seed'], warm_evidence=warm_evidence,
                  common_warm_pin_evaluations=sum(e['pin_evaluations'] for e in warm_evidence),
                  records=records, new_thermal_queries=sum(r['effort']['new_thermal_queries'] for r in records),
                  cold_start_comparison=False, detailed_routing_proven=False, timing_closed=False)
    write_new(output/'result.json', result)


def without_elapsed(value):
    if isinstance(value, dict):
        return {k: without_elapsed(v) for k, v in value.items() if not k.endswith('_seconds')}
    if isinstance(value, list):
        return [without_elapsed(v) for v in value]
    return value


def verify(input_path, plan_path, result_path, output):
    source, plan = check_plan(input_path, plan_path)
    result = read(result_path)
    if result['plan_sha256'] != digest(raw(plan_path)) or result['seed'] != plan['seed']:
        raise ValueError('Result plan mismatch')
    warm_rows, warm_thermal, warm_evidence = warm_start(source, plan)
    if without_elapsed(warm_evidence) != without_elapsed(result['warm_evidence']):
        raise ValueError('Warm-start replay mismatch')
    checks = []
    for arm, record in zip(ARMS, result['records'], strict=True):
        responses = iter(record['thermal_records'])
        consumed = 0
        def saved(data):
            nonlocal consumed
            item = next(responses)
            if item['evaluated_case_sha256'] != object_hash(data) or item['thermal']['evaluated_case_sha256'] != object_hash(data):
                raise ValueError('Query input replay mismatch')
            admitted_response(data, plan, item['thermal'])
            consumed += 1
            return item['thermal']
        entries = prepare_pool(source, plan, arm == ARMS[1])
        replay = run_arm(source, plan, arm, entries, warm_rows, warm_thermal, saved)
        if without_elapsed(record) != without_elapsed(replay) or next(responses, None) is not None:
            raise ValueError('Arm events, costs or complete joint-point replay mismatch')
        checks.append(dict(arm=arm, saved_responses_checked=consumed, replay_passed=True))
    if (result['new_thermal_queries'] != sum(c['saved_responses_checked'] for c in checks)
            or result['common_warm_pin_evaluations'] != sum(e['pin_evaluations'] for e in warm_evidence)):
        raise ValueError('Total cost receipt mismatch')
    write_new(output, dict(status='verified_saved_response_replay', plan_sha256=result['plan_sha256'],
                           result_sha256=digest(raw(result_path)), new_thermal_queries=0, checks=checks))
    print(json.dumps(checks, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=Path(INPUT))
    p.add_argument('--plan', type=Path, default=Path(PLAN))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify', action='store_true')
    p.add_argument('--hits', type=Path)
    p.add_argument('--result', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.freeze:
        freeze(a.input, a.plan, a.output)
    elif a.execute and a.hits:
        execute(a.input, a.plan, a.hits, a.output)
    elif a.verify and a.result:
        verify(a.input, a.plan, a.result, a.output)
    else:
        p.error('Execution requires hits; verification requires result')


if __name__ == '__main__':
    main()
