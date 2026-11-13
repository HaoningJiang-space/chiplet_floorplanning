"""Freeze, execute and replay a paired temperature-feedback parent experiment."""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import time

from atplace_incremental_pins import IncidentPinRepair
from atplace_pin_geometry import make_thermal_case, pin_objective
from atplace_routing_screen import screen_metric
from atplace_search import identities, profile
from atplace_temperature_feedback import run_search
from chiplet_floorplanning.model import parse_case
from run_atplace_orientation import (INPUT, PLAN as PRIOR_PLAN, check_plan as check_prior,
                                     admitted_response, without_elapsed)
from run_atplace_routing_boundary import nominal_response, read
from run_atplace_search import digest, object_hash, raw, write_new
from solve_tap_fv_hits import run

PRIOR_RESULT = 'docs/evidence/atplace-case1-orientation-v1.json'
HISTORY_PATHS = tuple('docs/evidence/atplace-case1-'+name+'-v1.json' for name in
                      ('search', 'crossover', 'slack', 'guided-slack', 'constrained-selection', 'orientation'))
PLAN = 'docs/evidence/atplace-case1-temperature-feedback-plan-v1.json'
PROTOCOL = 'atplace-case1-temperature-feedback-v1'
PIN_ACCEPTANCE = 'docs/evidence/atplace-case1-incremental-history-v1.json'
METHODS = ('temperature_blind', 'temperature_guided')
SOURCES = ('tools/atplace_incremental_pins.py', 'tools/atplace_temperature_feedback.py',
           'tools/run_atplace_temperature_feedback.py', 'docs/atplace-case1-temperature-feedback-protocol.md')


def source_hashes():
    return {p: digest(raw(p)) for p in SOURCES}


def load_warm(source, prior):
    """One repair pass on every stored A-F/orientation state; no new heat.

    Preserve original and repaired joint states. This is an archive augmentation,
    not exhaustive orientation minimization or a mathematical fixed-point closure.
    """
    started = time.perf_counter()
    engine = IncidentPinRepair(source, prior['gap_um'])
    responses, rows, seen, input_seen, originals, diagnostics = {}, [], {}, {}, [], []
    raw_rows = net_evaluations = routing_rejections = 0
    def save(key, summary):
        if key in responses and responses[key]['thermal']['peak_power_layer_c'] != summary['peak_power_layer_c']:
            raise ValueError('Historical thermal-equivalent responses disagree')
        responses[key] = dict(response_id='warm/'+key, thermal=deepcopy(summary))
    def append(poses, metric, summary, provenance):
        full, thermal = identities(source, poses, prior['gap_um'])
        key = object_hash(full)
        if key not in seen:
            seen[key] = len(rows)
            rows.append(dict(row_index=len(rows), placement=deepcopy(poses),
                             layout_key=[list(x) for x in full], thermal_key=[list(x) for x in thermal],
                             pin_length_m=metric['total_pin_manhattan_m'],
                             pin_length_um_decimal=metric['total_pin_manhattan_um_decimal'],
                             peak_c=summary['peak_power_layer_c'], thermal_response_id='warm/'+object_hash(thermal),
                             thermal_cache_hit=True, thermal_queries_so_far=0, provenance=provenance))
        return rows[seen[key]]
    for path in HISTORY_PATHS:
        history = read(path)
        for record in history['records']:
            for previous in record['rows']:
                raw_rows += 1
                full, thermal = identities(source, previous['placement'], prior['gap_um'])
                key, thermal_hash = object_hash(full), object_hash(thermal)
                if key in input_seen:
                    if previous['peak_c'] != input_seen[key]:
                        raise ValueError('Repeated historical joint state disagrees')
                    continue
                input_seen[key] = previous['peak_c']
                if 'thermal_solve_id' in previous:
                    owner = next(r for r in record['rows'] if r['thermal_solve_id'] == previous['thermal_solve_id']
                                 and not r['thermal_cache_hit'])
                    if object_hash(identities(source, owner['placement'], prior['gap_um'])[1]) != thermal_hash:
                        raise ValueError('Historical cache row changed physical thermal identity')
                    data, summary = nominal_response(source, prior, owner, record)
                    admitted_response(data, prior, summary)
                    save(thermal_hash, summary)
                elif not previous['thermal_response_id'].startswith('warm/'):
                    item = next(t for t in record['thermal_records'] if t['response_id'] == previous['thermal_response_id'])
                    data = make_thermal_case(source, previous['placement'], prior['gap_um'], prior['resolution'])
                    summary = item['thermal']
                    if object_hash(data) != item['evaluated_case_sha256'] or object_hash(data) != summary['evaluated_case_sha256']:
                        raise ValueError('Historical query input mismatch')
                    admitted_response(data, prior, summary)
                    save(thermal_hash, summary)
                summary = responses[thermal_hash]['thermal']
                if previous['peak_c'] != summary['peak_power_layer_c']:
                    raise ValueError('Historical row/response mismatch')
                metric = pin_objective(source, previous['placement'], prior['gap_um'])
                if previous['pin_length_m'] != metric['total_pin_manhattan_m']:
                    raise ValueError('Historical pin objective mismatch')
                routing = screen_metric(metric, source['interposer_width_um'], source['interposer_height_um'], prior['resources'])
                provenance = dict(path=path, method=record.get('method', record.get('arm')),
                                  row_index=previous['row_index'], orientation_repaired=False)
                if routing['admitted']:
                    originals.append(dict(append(previous['placement'], metric, summary, provenance), provenance=provenance))
                else:
                    routing_rejections += 1
                repaired = engine.repair(previous['placement'])
                repaired_routing = screen_metric(repaired['metric'], source['interposer_width_um'], source['interposer_height_um'], prior['resources'])
                net_evaluations += len(source['nets'])+repaired['effort']['net_length_evaluations']
                if repaired_routing['admitted']:
                    append(repaired['placement'], repaired['metric'], summary, dict(provenance, orientation_repaired=True))
                else:
                    routing_rejections += 1
                diagnostics.append(dict(provenance=provenance, peak_c=previous['peak_c'],
                                        before_length_m=metric['total_pin_manhattan_m'],
                                        after_length_m=repaired['metric']['total_pin_manhattan_m'],
                                        repaired_routing_admitted=repaired_routing['admitted']))
    cost = dict(raw_history_rows=raw_rows, historical_unique_full_states=len(input_seen),
                joint_states=len(rows), physical_responses=len(responses), new_thermal_queries=0,
                full_pin_metric_calls=2*len(input_seen), routing_checks=2*len(input_seen),
                routing_rejected_states=routing_rejections, net_length_evaluations=net_evaluations,
                newly_length_feasible_inputs=sum(d['before_length_m'] > prior['length_cap_m'] >= d['after_length_m']
                                                and d['repaired_routing_admitted'] for d in diagnostics),
                original_physical_comparison=profile(originals, prior['length_cap_m'], prior['temperature_cap_c']),
                repaired_archive_physical_comparison=profile(rows, prior['length_cap_m'], prior['temperature_cap_c']),
                diagnostics=diagnostics, elapsed_seconds=time.perf_counter()-started)
    return rows, responses, cost


def freeze(input_path, plan_path):
    source, prior = check_prior(input_path, PRIOR_PLAN)
    acceptance = read(PIN_ACCEPTANCE)
    if (acceptance['status'] != 'all_historical_and_pool_inputs_exactly_match'
            or acceptance['operator_sha256'] != digest(raw('tools/atplace_incremental_pins.py'))):
        raise ValueError('Incremental pin equivalence is not current')
    archive, _, cost = load_warm(source, prior)
    rows = initial_rows(archive)
    plan = {k: deepcopy(prior[k]) for k in ('seed', 'gap_um', 'grid_um', 'step_um', 'resolution', 'length_cap_m',
                                           'temperature_cap_c', 'hits_commit', 'resources', 'design_sha256')}
    plan.update(protocol=PROTOCOL, starting_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                input_sha256=digest(raw(input_path)), prior_plan_sha256=digest(raw(PRIOR_PLAN)),
                prior_result_sha256=digest(raw(PRIOR_RESULT)), sources_sha256=source_hashes(),
                history_sha256={p: digest(raw(p)) for p in HISTORY_PATHS},
                pin_acceptance_sha256=digest(raw(PIN_ACCEPTANCE)),
                methods=list(METHODS), thermal_budget_per_arm=16, parent_cap=130, proposal_cap=128,
                geometry_check_cap=3120, net_length_evaluation_cap=2703360,
                improvement_tolerance_k=1e-6, warm_rows=rows, historical_archive_rows=archive,
                best_known_reference=cost['repaired_archive_physical_comparison'], warm_preflight=cost)
    write_new(plan_path, plan)
    print(dict(plan_sha256=digest(raw(plan_path)), **{k: v for k, v in cost.items() if k not in ('diagnostics', 'original_physical_comparison', 'repaired_archive_physical_comparison')}))


def initial_rows(archive):
    previous = read(PRIOR_RESULT)['records'][0]['rows']
    rows = []
    for label in ('B_repaired', 'D_repaired'):
        saved = next(r for r in previous if r.get('candidate_id') == label)
        row = next(r for r in archive if r['layout_key'] == saved['layout_key'])
        rows.append(dict(deepcopy(row), row_index=len(rows)))
    return rows


def check_plan(input_path, plan_path):
    source, prior = check_prior(input_path, PRIOR_PLAN)
    plan = read(plan_path)
    if (plan['protocol'] != PROTOCOL or plan['input_sha256'] != digest(raw(input_path))
            or plan['prior_plan_sha256'] != digest(raw(PRIOR_PLAN))
            or plan['prior_result_sha256'] != digest(raw(PRIOR_RESULT)) or plan['sources_sha256'] != source_hashes()
            or plan['pin_acceptance_sha256'] != digest(raw(PIN_ACCEPTANCE))
            or plan['history_sha256'] != {p: digest(raw(p)) for p in HISTORY_PATHS}):
        raise ValueError('Frozen implementation or historical inputs changed')
    archive, responses, cost = load_warm(source, prior)
    rows = initial_rows(archive)
    if rows != plan['warm_rows'] or archive != plan['historical_archive_rows']:
        raise ValueError('Common archive replay mismatch')
    return source, plan, rows, responses, cost


def execute(input_path, plan_path, hits, output):
    source, plan, rows, responses, cost = check_plan(input_path, plan_path)
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != plan['hits_commit'] or subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Expected clean pinned HiTS')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for method in METHODS:
        queries = 0
        def solve(data):
            nonlocal queries
            summary, _, _, _ = run(parse_case(data), hits)
            admitted_response(data, plan, summary)
            summary['evaluated_case_sha256'] = object_hash(data)
            write_new(output/f'{method}-{queries:02d}.json', dict(case_data=data, thermal=summary))
            queries += 1
            print(method, queries, summary['peak_power_layer_c'], flush=True)
            return summary
        record = run_search(source, plan, method, rows, responses, solve)
        records.append(record)
        write_new(output/(method+'.json'), record)
    write_new(output/'result.json', dict(status='completed_paired_parent_feedback',
              execution_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              plan_sha256=digest(raw(plan_path)), hits_commit=sha, common_warm_cost=cost, records=records,
              new_thermal_queries=sum(r['effort']['new_thermal_queries'] for r in records),
              cold_start_comparison=False, detailed_routing_proven=False, timing_closed=False))


def verify(input_path, plan_path, result_path, output):
    source, plan, rows, responses, cost = check_plan(input_path, plan_path)
    result = read(result_path)
    if result['plan_sha256'] != digest(raw(plan_path)) or without_elapsed(result['common_warm_cost']) != without_elapsed(cost):
        raise ValueError('Plan or shared-cost mismatch')
    checked = []
    for method, record in zip(METHODS, result['records'], strict=True):
        saved = iter(record['thermal_records'])
        def solve(data):
            item = next(saved)
            if object_hash(data) != item['evaluated_case_sha256'] or object_hash(data) != item['thermal']['evaluated_case_sha256']:
                raise ValueError('Actual thermal input replay mismatch')
            admitted_response(data, plan, item['thermal'])
            return item['thermal']
        replay = run_search(source, plan, method, rows, responses, solve)
        if without_elapsed(replay) != without_elapsed(record) or next(saved, None) is not None:
            raise ValueError('Parent, candidate, response, cost or joint-point replay mismatch')
        checked.append(dict(method=method, replay_passed=True, saved_responses=len(record['thermal_records'])))
    if result['new_thermal_queries'] != sum(c['saved_responses'] for c in checked):
        raise ValueError('Total query mismatch')
    write_new(output, dict(status='verified_saved_response_replay', new_thermal_queries=0,
                           result_sha256=digest(raw(result_path)), plan_sha256=digest(raw(plan_path)), checks=checked))
    print(checked)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=Path(INPUT))
    p.add_argument('--plan', type=Path, default=Path(PLAN))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--result', type=Path)
    p.add_argument('--hits', type=Path)
    a = p.parse_args()
    if a.freeze:
        freeze(a.input, a.plan)
    elif a.execute and a.hits and a.output:
        execute(a.input, a.plan, a.hits, a.output)
    elif a.verify and a.result and a.output:
        verify(a.input, a.plan, a.result, a.output)
    else:
        p.error('Execute needs hits/output; verify needs result/output')
