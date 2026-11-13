"""Paired local parent-expansion ablation driven by actual thermal responses."""
from copy import deepcopy
import random
import time

from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import candidate_pool
from atplace_pin_geometry import make_thermal_case
from atplace_search import profile
from run_atplace_search import object_hash


def priority(row):
    return row['peak_c'], row['pin_length_m'], object_hash(row['layout_key'])


def run_search(source, plan, method, warm_rows, warm_responses, solve):
    """Both arms expand new evaluated states; only parent selection uses T.

    Historical responses are shared as a cache, not as free search parents or
    attained points. Parent-local orders depend on full state, not call history.
    """
    if method not in ('temperature_blind', 'temperature_guided'):
        raise ValueError('Unknown parent-expansion method')
    started = time.perf_counter()
    engine = IncidentPinRepair(source, plan['gap_um'])
    rows, events, queries, parents = deepcopy(warm_rows), [], [], []
    cache = deepcopy(warm_responses)
    seen = {object_hash(r['layout_key']): r['row_index'] for r in rows}
    geometry_checks = 0
    rng = random.Random(plan['seed'])
    net_work = 0
    per_candidate_net_work = 2*len(source['nets'])+sum(
        (3 if c['width_um'] == c['height_um'] else 1)*len(engine.incident[c['name']]) for c in source['chiplets'])
    def add_parent(row, generation):
        nonlocal geometry_checks
        if (len(parents) >= plan['parent_cap']
                or geometry_checks+4*len(source['chiplets']) > plan['geometry_check_cap']):
            return False
        seed = int(object_hash([plan['seed'], row['layout_key']]), 16)
        moves, checks = candidate_pool(source, [dict(label=str(row['row_index']), placement=row['placement'])],
                                       plan['gap_um'], plan['step_um'], seed)
        geometry_checks += checks
        parents.append(dict(row_index=row['row_index'], generation=generation, moves=moves, cursor=0))
        return True
    for row in rows:
        add_parent(row, 0)
    initial_parent_count = len(parents)
    checkpoints = []
    cost_stop = None
    while len(queries) < plan['thermal_budget_per_arm'] and len(events) < plan['proposal_cap']:
        if net_work+per_candidate_net_work > plan['net_length_evaluation_cap']:
            cost_stop = 'net_length_evaluation_cap'
            break
        available = [p for p in parents if p['cursor'] < len(p['moves'])]
        if not available:
            break
        available.sort(key=lambda p: object_hash(rows[p['row_index']]['layout_key']))
        parent = (rng.choice(available) if method == 'temperature_blind' else
                  min(available, key=lambda p: priority(rows[p['row_index']])))
        origin = rows[parent['row_index']]
        move = parent['moves'][parent['cursor']]
        parent['cursor'] += 1
        prepared = engine.prepare(move['placement'], plan['resources'])
        net_work += prepared['effort']['net_length_evaluations']
        event = dict(parent_row=origin['row_index'], parent_generation=parent['generation'],
                     move={k: move[k] for k in ('chiplet', 'field', 'delta_um')}, **prepared)
        events.append(event)
        if not prepared['routing']['admitted']:
            event['status'] = 'rejected_necessary_routing'
            continue
        if prepared['pin_length_m'] > plan['length_cap_m']:
            event['status'] = 'rejected_length_cap'
            continue
        full, thermal = object_hash(prepared['layout_key']), object_hash(prepared['thermal_key'])
        if full in seen:
            event.update(status='duplicate_full_state', row_index=seen[full])
            continue
        hit = thermal in cache
        if not hit:
            data = make_thermal_case(source, prepared['placement'], plan['gap_um'], plan['resolution'])
            response = solve(data)
            response_id = f'{method}/{len(queries)}'
            queries.append(dict(response_id=response_id, thermal_key=prepared['thermal_key'],
                                evaluated_case_sha256=object_hash(data), thermal=response))
            cache[thermal] = dict(response_id=response_id, thermal=response)
        item = cache[thermal]
        row = dict(row_index=len(rows), placement=prepared['placement'], layout_key=prepared['layout_key'],
                   thermal_key=prepared['thermal_key'], peak_c=item['thermal']['peak_power_layer_c'],
                   pin_length_m=prepared['pin_length_m'], pin_length_um_decimal=prepared['pin_length_um_decimal'],
                   thermal_response_id=item['response_id'], thermal_cache_hit=hit,
                   thermal_queries_so_far=len(queries), parent_row=origin['row_index'])
        rows.append(row)
        seen[full] = row['row_index']
        colder = row['peak_c'] < origin['peak_c']-plan['improvement_tolerance_k']
        promoted = add_parent(row, parent['generation']+1)
        event.update(status='thermal_cache_hit' if hit else 'thermal_evaluated', row_index=row['row_index'],
                     colder_than_parent=colder, promoted_to_parent=bool(promoted))
        if not hit:
            checkpoints.append(dict(new_thermal_queries=len(queries),
                                    physical_comparison=profile(rows, plan['length_cap_m'], plan['temperature_cap_c'])))
    return dict(method=method, rows=rows, events=events, thermal_records=queries, checkpoints=checkpoints,
                status=(cost_stop or ('complete_thermal_budget' if len(queries) == plan['thermal_budget_per_arm'] else
                        'proposal_cap' if len(events) == plan['proposal_cap'] else 'exhausted_parent_neighborhoods')),
                physical_comparison=profile(rows, plan['length_cap_m'], plan['temperature_cap_c']),
                parent_expansions=[dict(row_index=p['row_index'], generation=p['generation'],
                                        legal_moves=len(p['moves']), consumed_moves=p['cursor']) for p in parents],
                effort=dict(new_thermal_queries=len(queries), initial_parents=initial_parent_count,
                            added_parents=len(parents)-initial_parent_count, geometry_checks=geometry_checks,
                            proposals=len(events), routing_checks=len(events),
                            net_length_evaluations=sum(e['effort']['net_length_evaluations'] for e in events),
                            duplicate_full_states=sum(e['status'] == 'duplicate_full_state' for e in events),
                            thermal_cache_hits=sum(e['status'] == 'thermal_cache_hit' for e in events),
                            routing_rejections=sum(e['status'] == 'rejected_necessary_routing' for e in events),
                            length_rejections=sum(e['status'] == 'rejected_length_cap' for e in events),
                            minimum_candidate_length_slack_m=min((plan['length_cap_m']-e['pin_length_m'] for e in events), default=None),
                            setup_seconds=engine.setup_seconds,
                            candidate_preparation_seconds=sum(e['preparation_seconds'] for e in events),
                            total_seconds=time.perf_counter()-started))
