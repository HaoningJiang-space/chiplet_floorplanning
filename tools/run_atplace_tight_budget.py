"""A new reference-cost constraint, reusing the frozen feedback search unchanged."""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import time

from atplace_pin_geometry import make_thermal_case, pin_objective
from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import candidate_pool
from atplace_routing_screen import screen_metric
from atplace_search import identities, profile
from atplace_temperature_feedback import run_search
from chiplet_floorplanning.model import parse_case
from run_atplace_orientation import admitted_response, without_elapsed
from run_atplace_routing_boundary import read
from run_atplace_search import digest, object_hash, raw, write_new
from run_atplace_temperature_feedback import INPUT, METHODS, PLAN as PRIOR_PLAN, check_plan as check_prior
from solve_tap_fv_hits import run

PRIOR_RESULT = 'docs/evidence/atplace-case1-temperature-feedback-v1.json'
PRIOR_REPLAY = 'docs/evidence/atplace-case1-temperature-feedback-replay-v1.json'
PLAN = 'docs/evidence/atplace-case1-tight-budget-plan-v1.json'
PROTOCOL = 'atplace-case1-tight-reference-cost-v1'
SOURCES = ('tools/run_atplace_tight_budget.py', 'docs/atplace-case1-tight-budget-protocol.md')


def source_hashes():
    return {p: digest(raw(p)) for p in SOURCES}


def zero_heat_neighborhood(source, plan, rows):
    """Describe constraint activity without choosing the cap from these results."""
    engine = IncidentPinRepair(source, plan['gap_um'])
    entries, checks = [], 0
    for row in rows:
        seed = int(object_hash([plan['seed'], row['layout_key']]), 16)
        moves, attempted = candidate_pool(source, [dict(label=str(row['row_index']), placement=row['placement'])],
                                          plan['gap_um'], plan['step_um'], seed)
        checks += attempted
        for move in moves:
            entry = engine.prepare(move['placement'], plan['resources'])
            entry.update(move={k: move[k] for k in ('chiplet', 'field', 'delta_um')},
                         length_admitted=entry['pin_length_m'] <= plan['length_cap_m'])
            entries.append(entry)
    return dict(new_thermal_queries=0, geometry_checks=checks, candidates=len(entries),
                length_admitted=sum(e['length_admitted'] for e in entries),
                routing_admitted=sum(e['routing']['admitted'] for e in entries),
                net_length_evaluations=sum(e['effort']['net_length_evaluations'] for e in entries),
                entries=entries)


def load_history(input_path):
    """Admit the reviewed responses; never turn the archive into search parents."""
    started = time.perf_counter()
    source, prior, _, responses, prior_cost = check_prior(input_path, PRIOR_PLAN)
    archive = deepcopy(prior['historical_archive_rows'])
    result, replay = read(PRIOR_RESULT), read(PRIOR_REPLAY)
    if (result['plan_sha256'] != digest(raw(PRIOR_PLAN))
            or replay['result_sha256'] != digest(raw(PRIOR_RESULT))
            or replay['status'] != 'verified_saved_response_replay'):
        raise ValueError('Reviewed feedback result is not bound to its plan/replay')
    seen = {object_hash(row['layout_key']) for row in archive}
    checked, new_responses = 0, 0
    for record in result['records']:
        for query in record['thermal_records']:
            owner = next(row for row in record['rows']
                         if row['thermal_response_id'] == query['response_id'] and not row['thermal_cache_hit'])
            data = make_thermal_case(source, owner['placement'], prior['gap_um'], prior['resolution'])
            thermal = identities(source, owner['placement'], prior['gap_um'])[1]
            if (object_hash(data) != query['evaluated_case_sha256']
                    or object_hash(data) != query['thermal']['evaluated_case_sha256']
                    or object_hash(thermal) != object_hash(query['thermal_key'])):
                raise ValueError('Reviewed query physical input mismatch')
            admitted_response(data, prior, query['thermal'])
            key = object_hash(thermal)
            if key in responses:
                if responses[key]['thermal']['peak_power_layer_c'] != query['thermal']['peak_power_layer_c']:
                    raise ValueError('Historical same-geometry temperatures disagree')
            else:
                new_responses += 1
                responses[key] = dict(response_id='warm/'+key, thermal=deepcopy(query['thermal']))
        for row in record['rows']:
            full, thermal = identities(source, row['placement'], prior['gap_um'])
            key = object_hash(full)
            if key in seen:
                continue
            metric = pin_objective(source, row['placement'], prior['gap_um'])
            routing = screen_metric(metric, source['interposer_width_um'], source['interposer_height_um'], prior['resources'])
            item = responses[object_hash(thermal)]
            if (metric['total_pin_manhattan_m'] != row['pin_length_m']
                    or metric['total_pin_manhattan_um_decimal'] != row['pin_length_um_decimal']
                    or row['peak_c'] != item['thermal']['peak_power_layer_c'] or not routing['admitted']):
                raise ValueError('Reviewed joint state failed pins/routing/response admission')
            archive.append(dict(row_index=len(archive), placement=deepcopy(row['placement']),
                                layout_key=[list(x) for x in full], thermal_key=[list(x) for x in thermal],
                                pin_length_m=row['pin_length_m'], pin_length_um_decimal=row['pin_length_um_decimal'],
                                peak_c=row['peak_c'], thermal_response_id=item['response_id'],
                                thermal_cache_hit=True, thermal_queries_so_far=0,
                                provenance=dict(path=PRIOR_RESULT, method=record['method'], row_index=row['row_index'])))
            seen.add(key)
            checked += 1
    cost = dict(prior_archive=prior_cost, added_joint_states=checked, added_physical_responses=new_responses,
                full_pin_metric_calls=checked, routing_checks=checked,
                net_length_evaluations=checked*len(source['nets']), physical_responses=len(responses),
                joint_states=len(archive), new_thermal_queries=0, elapsed_seconds=time.perf_counter()-started)
    return source, prior, archive, responses, cost


def reference_configuration(prior):
    """Use the pre-feedback shortest admissible reference, not a new arm's winner."""
    anchor = deepcopy(prior['best_known_reference']['length_at_temperature']['selected'])
    if anchor is None or anchor['peak_c'] > prior['temperature_cap_c']:
        raise ValueError('Missing temperature-admissible reference')
    row = dict(deepcopy(anchor), row_index=0)
    return dict(length_cap_m=anchor['pin_length_m'], warm_rows=[row], budget_reference=anchor,
                budget_rule='no_more_pin_length_than_pre_feedback_temperature_admissible_shortest_reference',
                physical_capacity_limit=False)


def configuration(input_path, source, prior, archive, responses):
    config = {k: deepcopy(prior[k]) for k in (
        'seed', 'gap_um', 'grid_um', 'step_um', 'resolution', 'temperature_cap_c', 'hits_commit',
        'resources', 'design_sha256', 'thermal_budget_per_arm', 'parent_cap', 'proposal_cap',
        'geometry_check_cap', 'net_length_evaluation_cap', 'improvement_tolerance_k')}
    config.update(reference_configuration(prior))
    config.update(protocol=PROTOCOL, input_sha256=digest(raw(input_path)),
                  prior_plan_sha256=digest(raw(PRIOR_PLAN)), prior_result_sha256=digest(raw(PRIOR_RESULT)),
                  prior_replay_sha256=digest(raw(PRIOR_REPLAY)), sources_sha256=source_hashes(),
                  methods=list(METHODS), historical_archive_rows=archive,
                  response_cache_sha256=object_hash(responses),
                  best_known_reference=profile(archive, config['length_cap_m'], config['temperature_cap_c']))
    for row in config['warm_rows']:
        metric = pin_objective(source, row['placement'], config['gap_um'])
        routing = screen_metric(metric, source['interposer_width_um'], source['interposer_height_um'], config['resources'])
        if (metric['total_pin_manhattan_m'] != row['pin_length_m']
                or row['pin_length_m'] > config['length_cap_m'] or not routing['admitted']
                or responses[object_hash(row['thermal_key'])]['thermal']['peak_power_layer_c'] != row['peak_c']):
            raise ValueError('Common start does not satisfy the new physical/geometric constraints')
    return config


def freeze(input_path, plan_path):
    source, prior, archive, responses, cost = load_history(input_path)
    plan = configuration(input_path, source, prior, archive, responses)
    plan.update(starting_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                common_history_cost=cost,
                zero_heat_neighborhood=zero_heat_neighborhood(source, plan, plan['warm_rows']))
    write_new(plan_path, plan)
    print(dict(plan_sha256=digest(raw(plan_path)), length_cap_m=plan['length_cap_m'],
               initial_points=[(r['peak_c'], r['pin_length_m']) for r in plan['warm_rows']],
               neighborhood={k: v for k, v in plan['zero_heat_neighborhood'].items() if k != 'entries'}))


def check_plan(input_path, plan_path):
    source, prior, archive, responses, cost = load_history(input_path)
    plan = read(plan_path)
    config = configuration(input_path, source, prior, archive, responses)
    if any(plan[k] != value for k, value in config.items()):
        raise ValueError('Frozen tight-budget inputs, implementation, budget or initialization changed')
    if (without_elapsed(cost) != without_elapsed(plan['common_history_cost'])
            or without_elapsed(zero_heat_neighborhood(source, plan, plan['warm_rows']))
            != without_elapsed(plan['zero_heat_neighborhood'])):
        raise ValueError('Shared history or zero-heat neighborhood changed')
    return source, plan, plan['warm_rows'], responses, cost


def execute(input_path, plan_path, hits, output):
    source, plan, rows, responses, cost = check_plan(input_path, plan_path)
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != plan['hits_commit'] or subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Expected clean pinned HiTS')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for method in METHODS:
        count = 0
        def solve(data):
            nonlocal count
            summary, _, _, _ = run(parse_case(data), hits)
            admitted_response(data, plan, summary)
            summary['evaluated_case_sha256'] = object_hash(data)
            write_new(output/f'{method}-{count:02d}.json', dict(case_data=data, thermal=summary))
            count += 1
            print(method, count, summary['peak_power_layer_c'], flush=True)
            return summary
        record = run_search(source, plan, method, rows, responses, solve)
        records.append(record)
        write_new(output/(method+'.json'), record)
    write_new(output/'result.json', dict(status='completed_tight_reference_cost_comparison',
              execution_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              plan_sha256=digest(raw(plan_path)), hits_commit=sha, common_history_cost=cost,
              records=records, new_thermal_queries=sum(r['effort']['new_thermal_queries'] for r in records),
              cold_start_comparison=False, physical_capacity_limit=False,
              detailed_routing_proven=False, timing_closed=False))


def verify(input_path, plan_path, result_path, output):
    source, plan, rows, responses, cost = check_plan(input_path, plan_path)
    result = read(result_path)
    if result['plan_sha256'] != digest(raw(plan_path)) or without_elapsed(cost) != without_elapsed(result['common_history_cost']):
        raise ValueError('Frozen plan or common history mismatch')
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
            raise ValueError('Tight-budget decisions, joint points or costs changed')
        checked.append(dict(method=method, replay_passed=True, saved_responses=len(record['thermal_records'])))
    if result['new_thermal_queries'] != sum(c['saved_responses'] for c in checked):
        raise ValueError('Total query count changed')
    write_new(output, dict(status='verified_saved_response_replay', new_thermal_queries=0,
                           result_sha256=digest(raw(result_path)), plan_sha256=digest(raw(plan_path)), checks=checked))
    print(checked)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path(INPUT))
    parser.add_argument('--plan', type=Path, default=Path(PLAN))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify', action='store_true')
    parser.add_argument('--hits', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze(args.input, args.plan)
    elif args.execute and args.hits and args.output:
        execute(args.input, args.plan, args.hits, args.output)
    elif args.verify and args.result and args.output:
        verify(args.input, args.plan, args.result, args.output)
    else:
        parser.error('Execute needs hits/output; verify needs result/output')
