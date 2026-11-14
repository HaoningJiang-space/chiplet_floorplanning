"""One-factor 2 mm / 1 mm search comparison with charged response reuse."""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import time

from atplace_temperature_feedback import run_search
from chiplet_floorplanning.model import parse_case
from run_atplace_orientation import admitted_response, without_elapsed
from run_atplace_search import digest, object_hash, raw, write_new
from run_atplace_tight_budget import (
    INPUT, PLAN as TIGHT_PLAN, check_plan as check_tight, read, zero_heat_neighborhood,
)
from solve_tap_fv_hits import run

TIGHT_RESULT = 'docs/evidence/atplace-case1-tight-budget-v1.json'
TIGHT_REPLAY = 'docs/evidence/atplace-case1-tight-budget-replay-v1.json'
PLAN = 'docs/evidence/atplace-case1-step-size-plan-v1.json'
SOURCES = ('tools/run_atplace_step_size.py', 'tests/atplace_step_size_unittest.py',
           'docs/atplace-case1-step-size-protocol.md')
PARAMETERS = ('seed', 'gap_um', 'grid_um', 'resolution', 'length_cap_m', 'temperature_cap_c',
              'hits_commit', 'resources', 'design_sha256', 'thermal_budget_per_arm', 'parent_cap',
              'proposal_cap', 'geometry_check_cap', 'net_length_evaluation_cap',
              'improvement_tolerance_k', 'warm_rows', 'response_cache_sha256', 'best_known_reference')


def replay_record(source, plan, rows, responses, record):
    saved = iter(record['thermal_records'])
    def solve(data):
        item = next(saved)
        key = object_hash(data)
        if key != item['evaluated_case_sha256'] or key != item['thermal']['evaluated_case_sha256']:
            raise ValueError('Saved response does not match requested physical input')
        admitted_response(data, plan, item['thermal'])
        return item['thermal']
    replay = run_search(source, plan, 'temperature_guided', rows, responses, solve)
    if without_elapsed(replay) != without_elapsed(record) or next(saved, None) is not None:
        raise ValueError('Saved decisions, costs or joint points failed exact replay')
    return replay


def context(input_path):
    source, tight, rows, responses, cost = check_tight(input_path, TIGHT_PLAN)
    result, receipt = read(TIGHT_RESULT), read(TIGHT_REPLAY)
    if (result['plan_sha256'] != digest(raw(TIGHT_PLAN))
            or receipt['result_sha256'] != digest(raw(TIGHT_RESULT))
            or receipt['status'] != 'verified_saved_response_replay'):
        raise ValueError('Tight baseline is not bound to its frozen plan and replay')
    baseline = next(r for r in result['records'] if r['method'] == 'temperature_guided')
    started = time.perf_counter()
    replay_record(source, tight, rows, responses, baseline)
    cost['baseline_replay_seconds'] = time.perf_counter()-started
    return source, tight, rows, responses, cost, baseline


def reachability(source, start, reference):
    initial = {p['chiplet']: p for p in start['placement']}
    target = {p['chiplet']: p for p in reference['placement']}
    parity = [dict(chiplet=name, field=field, start_remainder_um=pose[field] % 2000,
                   reference_remainder_um=target[name][field] % 2000)
              for name, pose in initial.items() for field in ('centre_x_um', 'centre_y_um')
              if pose[field] % 2000 != target[name][field] % 2000]
    rectangle = [dict(chiplet=c['name'], start_rotation_deg=initial[c['name']]['rotation_deg'],
                      reference_rotation_deg=target[c['name']]['rotation_deg'])
                 for c in source['chiplets'] if c['width_um'] != c['height_um']
                 and initial[c['name']]['rotation_deg'] % 180 != target[c['name']]['rotation_deg'] % 180]
    return dict(coordinate_mod_2mm_mismatches=parity, rectangle_orientation_class_mismatches=rectangle,
                reference_reachability_proven=False)


def configuration(input_path, source, tight, responses, baseline):
    plan = {k: deepcopy(tight[k]) for k in PARAMETERS}
    plan.update(protocol='atplace-case1-fixed-step-size-v1', steps_um=[2000, 1000],
                method='temperature_guided', input_sha256=digest(raw(input_path)),
                dependencies_sha256={p: digest(raw(p)) for p in (TIGHT_PLAN, TIGHT_RESULT, TIGHT_REPLAY)},
                sources_sha256={p: digest(raw(p)) for p in SOURCES},
                baseline_record_sha256=object_hash(baseline), initial_response_count=len(responses),
                external_reuse='baseline_guided_exact_input_only_still_charged',
                reachability=reachability(source, tight['warm_rows'][0],
                    tight['best_known_reference']['temperature_at_length']['selected']))
    return plan


def neighborhoods(source, plan):
    return {str(step): zero_heat_neighborhood(source, dict(plan, step_um=step), plan['warm_rows'])
            for step in plan['steps_um']}


def freeze(input_path, plan_path):
    source, tight, _, responses, cost, baseline = context(input_path)
    plan = configuration(input_path, source, tight, responses, baseline)
    plan.update(starting_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                common_history_cost=cost, zero_heat_neighborhoods=neighborhoods(source, plan))
    write_new(plan_path, plan)
    print(dict(plan_sha256=digest(raw(plan_path)), baseline_replay_passed=True,
               initial_response_count=len(responses), actual_new_thermal_solves=0))


def check_plan(input_path, plan_path):
    source, tight, rows, responses, cost, baseline = context(input_path)
    plan = read(plan_path)
    expected = configuration(input_path, source, tight, responses, baseline)
    if any(plan[k] != value for k, value in expected.items()):
        raise ValueError('Step-size protocol, inputs or code changed after freeze')
    if (without_elapsed(cost) != without_elapsed(plan['common_history_cost'])
            or without_elapsed(neighborhoods(source, plan)) != without_elapsed(plan['zero_heat_neighborhoods'])):
        raise ValueError('Shared history or zero-heat diagnostic changed')
    return source, plan, rows, responses, cost, baseline


def saved_inputs(record):
    # Exact full-input reuse is intentionally narrower than physical-key caching.
    return {q['evaluated_case_sha256']: dict(thermal=q['thermal'], response_id=q['response_id'])
            for q in record['thermal_records']}


class ChargedOracle:
    """Reuse avoids computation, not a charged query or search admission.

    Only run_search can request a response. This lookup is never an initial
    response cache, search parent, attained point, or candidate-ranking signal.
    """
    def __init__(self, saved, fresh, admit):
        self.saved, self.fresh, self.admit = saved, fresh, admit
        self.receipts = []

    def __call__(self, data):
        key = object_hash(data)
        if key in self.saved:
            item = self.saved[key]
            summary = deepcopy(item['thermal'])
            provenance = dict(source='saved_baseline_response', source_response_id=item['response_id'])
        else:
            summary = self.fresh(data)
            summary['evaluated_case_sha256'] = key
            provenance = dict(source='new_local_solve', source_response_id=None)
        if summary['evaluated_case_sha256'] != key:
            raise ValueError('External response input mismatch')
        self.admit(data, summary)
        self.receipts.append(dict(charged_index=len(self.receipts)+1, evaluated_case_sha256=key, **provenance))
        return summary


def ledger(receipts):
    return dict(charged_evaluations=len(receipts),
                actual_new_thermal_solves=sum(r['source'] == 'new_local_solve' for r in receipts),
                saved_response_returns=sum(r['source'] == 'saved_baseline_response' for r in receipts),
                receipts=receipts)


def baseline_arm(baseline):
    receipts = [dict(charged_index=i+1, evaluated_case_sha256=q['evaluated_case_sha256'],
                     source='saved_baseline_response', source_response_id=q['response_id'])
                for i, q in enumerate(baseline['thermal_records'])]
    return dict(step_um=2000, execution='verified_historical_baseline', record=baseline, **ledger(receipts))


def comparison(arms):
    points = [a['record']['physical_comparison'] for a in arms]
    primary = [p['temperature_at_length']['selected'] for p in points]
    reverse = [p['length_at_temperature']['selected'] for p in points]
    return dict(delta_peak_1mm_minus_2mm_k=primary[1]['peak_c']-primary[0]['peak_c'],
                delta_reverse_length_1mm_minus_2mm_m=reverse[1]['pin_length_m']-reverse[0]['pin_length_m'])


def execute(input_path, plan_path, hits, output):
    source, plan, rows, responses, cost, baseline = check_plan(input_path, plan_path)
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != plan['hits_commit'] or subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Expected clean pinned HiTS')
    output.mkdir(parents=True, exist_ok=False)
    def fresh(data):
        summary, _, _, _ = run(parse_case(data), hits)
        summary['evaluated_case_sha256'] = object_hash(data)
        admitted_response(data, plan, summary)
        write_new(output/f'local-solve-{len(oracle.receipts):02d}.json', dict(case_data=data, thermal=summary))
        print('1mm local solve', len(oracle.receipts)+1, summary['peak_power_layer_c'], flush=True)
        return summary
    oracle = ChargedOracle(saved_inputs(baseline), fresh,
                           lambda data, summary: admitted_response(data, plan, summary))
    record = run_search(source, dict(plan, step_um=1000), 'temperature_guided', rows, responses, oracle)
    if len(oracle.receipts) != record['effort']['new_thermal_queries']:
        raise ValueError('Charged query accounting mismatch')
    arms = [baseline_arm(baseline), dict(step_um=1000, execution='new_search', record=record, **ledger(oracle.receipts))]
    write_new(output/'result.json', dict(status='completed_fixed_step_size_comparison', arms=arms,
              execution_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              plan_sha256=digest(raw(plan_path)), common_history_cost=cost, hits_commit=sha,
              comparison=comparison(arms),
              charged_evaluations=sum(a['charged_evaluations'] for a in arms),
              actual_new_thermal_solves=sum(a['actual_new_thermal_solves'] for a in arms),
              legacy_query_field_semantics='record.effort.new_thermal_queries_counts_charged_evaluations_not_new_solves',
              cold_start_comparison=False, physical_capacity_limit=False,
              detailed_routing_proven=False, timing_closed=False))


def verify(input_path, plan_path, result_path, output):
    source, plan, rows, responses, cost, baseline = check_plan(input_path, plan_path)
    result = read(result_path)
    if result['plan_sha256'] != digest(raw(plan_path)) or without_elapsed(cost) != without_elapsed(result['common_history_cost']):
        raise ValueError('Plan/history mismatch')
    base, fine = result['arms']
    if base != baseline_arm(baseline) or fine['step_um'] != 1000 or fine['execution'] != 'new_search':
        raise ValueError('Baseline or changed step mismatch')
    replay_record(source, dict(plan, step_um=1000), rows, responses, fine['record'])
    expected_receipts, saved = [], saved_inputs(baseline)
    for i, q in enumerate(fine['record']['thermal_records']):
        key = q['evaluated_case_sha256']
        if key in saved and q['thermal'] != saved[key]['thermal']:
            raise ValueError('Saved baseline response changed')
        expected_receipts.append(dict(charged_index=i+1, evaluated_case_sha256=key,
            source='saved_baseline_response' if key in saved else 'new_local_solve',
            source_response_id=saved[key]['response_id'] if key in saved else None))
    if any(fine[k] != value for k, value in ledger(expected_receipts).items()):
        raise ValueError('Response provenance or query charge changed')
    if (result['comparison'] != comparison(result['arms'])
            or result['charged_evaluations'] != sum(a['charged_evaluations'] for a in result['arms'])
            or result['actual_new_thermal_solves'] != sum(a['actual_new_thermal_solves'] for a in result['arms'])):
        raise ValueError('Comparison/accounting mismatch')
    write_new(output, dict(status='verified_saved_response_replay', actual_new_thermal_solves=0,
                           result_sha256=digest(raw(result_path)), plan_sha256=digest(raw(plan_path)),
                           checked_charged_responses=result['charged_evaluations'], steps_um=plan['steps_um']))
    print('Verified both full search trajectories and charged/actual-solve ledger; no new heat.')


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
