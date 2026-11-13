"""Bounded archive routing admission and fixed-candidate boundary sensitivity."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time

from atplace_pin_geometry import make_thermal_case
from atplace_routing_screen import DEFAULT_RESOURCES, RoutingScreenedEvaluator, screen_placement
from atplace_search import profile
from chiplet_floorplanning.model import parse_case
from run_atplace_constrained_selection import check_plan as check_f
from run_atplace_crossover import thermal_admitted
from run_atplace_search import digest, object_hash, raw, write_new
from solve_tap_fv_hits import run

PREFIX = 'docs/evidence/atplace-case1-'
F_PLAN = PREFIX+'constrained-selection-plan-v1.json'
INPUT = 'results/physical-calibration/atplace-import-v1/Case1.json'
PLAN = PREFIX+'routing-boundary-plan-v1.json'
HISTORIES = {label: PREFIX+name+'-v1.json' for label, name in (
    ('B', 'search'), ('D', 'slack'), ('E', 'guided-slack'), ('F', 'constrained-selection'))}
SOURCES = ('tools/atplace_routing_screen.py', 'tools/run_atplace_routing_boundary.py',
           'docs/atplace-case1-routing-boundary-protocol.md')
SCENARIOS = ('half_h', 'double_h', 'tim_contact')


def read(path):
    return json.loads(raw(path))


def variant_case(nominal, scenario):
    data = deepcopy(nominal)
    if scenario == 'half_h':
        data['thermal']['top_h_w_m2k'] *= .5
    elif scenario == 'double_h':
        data['thermal']['top_h_w_m2k'] *= 2
    elif scenario == 'tim_contact':
        layer = next(x for x in data['thermal']['layers'] if x['id'] == 'tim')
        layer['contact_resistance_above_m2k_w'] = layer.get('contact_resistance_above_m2k_w', 0)+5e-6
    else:
        raise ValueError('Unknown frozen boundary scenario')
    return data


def boundary_balance(data):
    t = data['thermal']
    rect = t['layers'][-1]['rect_mm']
    area = rect['width']*rect['height']/1e6
    power = sum(b['power_w'] for c in data['chiplets'] for b in c['blocks'])
    resistance = 1/(t['top_h_w_m2k']*area)
    return dict(power_w=power, top_h_w_m2k=t['top_h_w_m2k'], top_area_m2=area,
                convection_resistance_k_w=resistance,
                surface_mean_c=t['ambient_c']+power*resistance)


def freeze(input_path, plan_path):
    _, old, _ = check_f(input_path, F_PLAN)
    histories = {label: read(path) for label, path in HISTORIES.items()}
    if histories['F']['plan'] != old:
        raise ValueError('F archive and frozen plan disagree')
    finalists = []
    for label in ('base', 'B', 'D', 'E', 'F'):
        record = histories['F' if label == 'base' else label]['records'][-1]
        if record['seed'] != old['seed'] or record['status'] != 'complete_thermal_budget':
            raise ValueError('Expected completed single-seed history')
        row = record['rows'][0] if label == 'base' else record['physical_comparison']['temperature_at_length']['selected']
        finalists.append(dict(label=label, history='F' if label == 'base' else label,
                              row=deepcopy(row)))
    plan = dict(protocol='atplace-case1-routing-boundary-v1',
                starting_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                input_path=str(input_path), input_sha256=digest(raw(input_path)),
                sources_sha256={p: digest(raw(p)) for p in SOURCES},
                history_sha256={p: digest(raw(p)) for p in (*HISTORIES.values(), F_PLAN)},
                seed=old['seed'], gap_um=old['gap_um'], length_cap_m=old['length_cap_m'],
                temperature_cap_c=old['temperature_cap_c'], hits_commit=old['hits_commit'],
                resources=deepcopy(DEFAULT_RESOURCES), archive_thermal_budget=48,
                new_thermal_budget=15, scenarios=list(SCENARIOS), finalists=finalists,
                comparison='fixed archive filtering, not a new adaptive optimization run')
    write_new(plan_path, plan)
    print(json.dumps(dict(plan_sha256=digest(raw(plan_path)), seed=plan['seed'],
                         finalists=[(f['label'], f['row']['row_index']) for f in finalists],
                         new_thermal_budget=15)))


def check_plan(input_path, plan_path):
    plan = read(plan_path)
    if plan['protocol'] != 'atplace-case1-routing-boundary-v1' or digest(raw(input_path)) != plan['input_sha256']:
        raise ValueError('Frozen plan/input mismatch')
    for path, sha in (plan['sources_sha256'] | plan['history_sha256']).items():
        if digest(raw(path)) != sha:
            raise ValueError('Frozen file changed: '+path)
    check_f(input_path, F_PLAN)  # Includes all inherited geometry/thermal implementation hashes.
    if plan['scenarios'] != list(SCENARIOS) or plan['resources'] != DEFAULT_RESOURCES:
        raise ValueError('Frozen scenario/resource mismatch')
    return read(input_path), plan


def nominal_response(source, plan, row, record):
    """Match the exact physical case before accepting a historical response."""
    nominal = make_thermal_case(source, row['placement'], plan['gap_um'])
    thermal = record['thermal_records'][row['thermal_solve_id']]['thermal']
    b = boundary_balance(nominal)
    if (thermal['evaluated_case_sha256'] != object_hash(nominal)
            or not thermal_admitted(thermal, b['power_w'], b['surface_mean_c'])
            or thermal['peak_power_layer_c'] != row['peak_c']):
        raise ValueError('Nominal physical input/temperature receipt mismatch')
    return nominal, thermal


def screen(input_path, plan_path, output):
    source, plan = check_plan(input_path, plan_path)
    started = time.perf_counter()
    records = {label: read(path)['records'][-1] for label, path in HISTORIES.items()}
    active_row = active_record = None
    nominal_callbacks = 0
    def reuse(data):
        nonlocal nominal_callbacks
        nominal, thermal = nominal_response(source, plan, active_row, active_record)
        if data != nominal:
            raise ValueError('Screened evaluator submitted a different physical case')
        nominal_callbacks += 1
        return deepcopy(thermal)
    evaluator = RoutingScreenedEvaluator(source, plan['gap_um'], reuse, plan['resources'])
    reports, eligible = [], []
    for row in records['F']['rows']:
        active_row, active_record = row, records['F']
        evaluated = evaluator.evaluate(row['placement'])
        receipt = evaluated['routing']
        reports.append(dict(row_index=row['row_index'], routing=receipt))
        if receipt['admitted']:
            if (evaluated['metric']['total_pin_manhattan_m'] != row['pin_length_m']
                    or evaluated['thermal_result']['peak_power_layer_c'] != row['peak_c']):
                raise ValueError('Recomputed nominal joint point differs')
            eligible.append(row)
    finalists = []
    for f in plan['finalists']:
        active_row, active_record = f['row'], records[f['history']]
        evaluated = evaluator.evaluate(active_row['placement'])
        finalists.append(dict(label=f['label'], row=deepcopy(active_row), routing=evaluated['routing']))
    filtered = profile(eligible, plan['length_cap_m'], plan['temperature_cap_c'])
    result = dict(status='completed_necessary_routing_screen', plan_sha256=digest(raw(plan_path)),
                  seed=plan['seed'], historical_thermal_queries=records['F']['effort']['thermal_queries'],
                  new_thermal_queries=0, archive_rows=len(reports), admitted_rows=len(eligible),
                  screening_calls=evaluator.routing_checks, nominal_response_callbacks=nominal_callbacks,
                  screening_rejections=evaluator.routing_rejections,
                  filtered_physical_comparison=filtered,
                  archive_joint_metrics_unchanged=filtered == records['F']['physical_comparison'],
                  rows=reports, finalists=finalists, elapsed_seconds=time.perf_counter()-started,
                  detailed_routing_proven=False, adaptive_search_rerun=False)
    write_new(output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'finalists', 'filtered_physical_comparison')}, indent=2))


def sensitivity(input_path, plan_path, screen_path, hits, output):
    source, plan = check_plan(input_path, plan_path)
    screening = read(screen_path)
    if screening['plan_sha256'] != digest(raw(plan_path)) or screening['status'] != 'completed_necessary_routing_screen':
        raise ValueError('Routing acceptance receipt mismatch')
    sha = subprocess.check_output(['git', '-C', str(hits), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != plan['hits_commit'] or subprocess.check_output(['git', '-C', str(hits), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Expected clean pinned local HiTS source')
    records = {label: read(path)['records'][-1] for label, path in HISTORIES.items()}
    points, queries = [], 0
    started = time.perf_counter()
    for f in plan['finalists']:
        row = f['row']
        receipt = screen_placement(source, row['placement'], plan['gap_um'], plan['resources'])
        if not receipt['admitted']:
            points.append(dict(label=f['label'], status='rejected_routing_necessary_condition', routing=receipt))
            continue
        nominal, saved = nominal_response(source, plan, row, records[f['history']])
        scenarios = {'nominal': dict(peak_c=row['peak_c'], boundary=boundary_balance(nominal),
                                    evaluated_case_sha256=object_hash(nominal), reused=True)}
        for name in plan['scenarios']:
            if queries >= plan['new_thermal_budget']:
                raise ValueError('Thermal budget exhausted')
            data = variant_case(nominal, name)
            summary, _, _, _ = run(parse_case(data), hits)
            queries += 1
            boundary = boundary_balance(data)
            if not thermal_admitted(summary, boundary['power_w'], boundary['surface_mean_c']):
                raise ValueError('Physical/numerical scenario admission failed')
            scenarios[name] = dict(peak_c=summary['peak_power_layer_c'], boundary=boundary,
                                   evaluated_case_sha256=object_hash(data), reused=False, thermal=summary)
            print(f['label'], name, scenarios[name]['peak_c'], flush=True)
        monotone = scenarios['half_h']['peak_c'] >= row['peak_c'] >= scenarios['double_h']['peak_c']
        if not monotone:
            raise ValueError('Positive fixed-power cooling monotonicity failed')
        points.append(dict(label=f['label'], status='evaluated', row_index=row['row_index'],
                           placement=row['placement'], pin_length_m=row['pin_length_m'],
                           length_feasible=row['pin_length_m'] <= plan['length_cap_m'],
                           routing=receipt, cooling_monotonicity_passed=monotone, scenarios=scenarios))
    evaluated = [p for p in points if p['status'] == 'evaluated']
    base = next((p for p in evaluated if p['label'] == 'base'), None)
    ordering = {}
    for name in ('nominal', *plan['scenarios']):
        order = sorted((p for p in evaluated if p['length_feasible']), key=lambda p: (p['scenarios'][name]['peak_c'], p['label']))
        flips = []
        for i, a in enumerate(order):
            for b in order[i+1:]:
                if a['scenarios']['nominal']['peak_c'] > b['scenarios']['nominal']['peak_c']:
                    flips.append([a['label'], b['label']])
        ordering[name] = dict(order_cold_to_hot=[p['label'] for p in order], reversed_pairs_vs_nominal=flips)
        for p in evaluated:
            p['scenarios'][name]['cooling_vs_same_scenario_base_k'] = (base['scenarios'][name]['peak_c']-p['scenarios'][name]['peak_c']) if base else None
            p['scenarios'][name]['original_temperature_cap_attained'] = p['scenarios'][name]['peak_c'] <= plan['temperature_cap_c']
    result = dict(status='completed_fixed_candidate_boundary_check', plan_sha256=digest(raw(plan_path)),
                  screen_sha256=digest(raw(screen_path)), hits_commit=sha, new_thermal_queries=queries,
                  elapsed_seconds=time.perf_counter()-started, points=points, ordering=ordering,
                  independently_calibrated=False, timing_closed=False, reoptimized=False,
                  scope='five frozen layouts, one historical seed, three declared stress scenarios; not calibrated uncertainty bounds')
    write_new(output, result)
    print(json.dumps(dict(new_thermal_queries=queries, ordering=ordering), indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=Path(INPUT))
    p.add_argument('--plan', type=Path, default=Path(PLAN))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--screen', action='store_true')
    mode.add_argument('--sensitivity', action='store_true')
    p.add_argument('--screen-result', type=Path)
    p.add_argument('--hits', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.freeze:
        freeze(a.input, a.plan)
    elif a.screen and a.output:
        screen(a.input, a.plan, a.output)
    elif a.sensitivity and a.screen_result and a.hits and a.output:
        sensitivity(a.input, a.plan, a.screen_result, a.hits, a.output)
    else:
        p.error('Provide output; sensitivity also needs screen-result and hits')


if __name__ == '__main__':
    main()
