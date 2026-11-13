"""Bound-preserving pin repair for the fixed uniform, isotropic die adapter.

This equivalence is not valid for nonuniform power maps or rotated anisotropy.
Pins and full layout identities still change; only the thermal response is shared.
"""
from copy import deepcopy
from decimal import Decimal
import random
import time

from atplace_pin_geometry import make_thermal_case, pin_objective
from atplace_routing_screen import screen_metric
from atplace_search import identities, profile
from run_atplace_search import object_hash


def repair(source, placement, gap_um):
    """One source-order coordinate scan; retain incumbent on exact length ties."""
    current = deepcopy(placement)
    _, thermal_key = identities(source, current, gap_um)
    original = metric = pin_objective(source, current, gap_um)
    trials, evaluations = [], 1
    for chip in source['chiplets']:
        index = next(i for i, p in enumerate(current) if p['chiplet'] == chip['name'])
        incumbent = current[index]['rotation_deg']
        angles = (0, 90, 180, 270) if chip['width_um'] == chip['height_um'] else sorted((incumbent, (incumbent+180) % 360))
        best_angle, best_metric = incumbent, metric
        for angle in angles:
            if angle == incumbent:
                continue
            trial = deepcopy(current)
            trial[index]['rotation_deg'] = angle
            candidate_metric = pin_objective(source, trial, gap_um)
            evaluations += 1
            trials.append(dict(chiplet=chip['name'], rotation_deg=angle,
                               pin_length_um_decimal=candidate_metric['total_pin_manhattan_um_decimal']))
            if Decimal(candidate_metric['total_pin_manhattan_um_decimal']) < Decimal(best_metric['total_pin_manhattan_um_decimal']):
                best_angle, best_metric = angle, candidate_metric
        current[index]['rotation_deg'], metric = best_angle, best_metric
        trials[-1]['selected_rotation_deg_after_chip'] = best_angle
    if identities(source, current, gap_um)[1] != thermal_key:
        raise ValueError('Orientation repair changed physical bounds')
    return dict(placement=current, initial_metric=original, metric=metric,
                pin_evaluations=evaluations, trials=trials)


def candidate_pool(source, anchors, gap_um, step_um, seed):
    """All legal single-die axis +/- step moves, then one common seeded shuffle."""
    candidates, attempts = [], 0
    for anchor in anchors:
        for chip in source['chiplets']:
            for field in ('centre_x_um', 'centre_y_um'):
                for delta in (-step_um, step_um):
                    attempts += 1
                    poses = deepcopy(anchor['placement'])
                    next(p for p in poses if p['chiplet'] == chip['name'])[field] += delta
                    try:
                        _, key = identities(source, poses, gap_um)
                    except ValueError:
                        continue
                    candidates.append(dict(candidate_id=f"{anchor['label']}:{chip['name']}:{field}:{delta:+d}",
                                           anchor=anchor['label'], chiplet=chip['name'], field=field,
                                           delta_um=delta, placement=poses, thermal_key=[list(x) for x in key]))
    random.Random(seed).shuffle(candidates)
    return candidates, attempts


def prepare(source, placement, plan, repaired):
    """Compute actual source pins once per trial, reuse final metric for routing."""
    started = time.perf_counter()
    if repaired:
        value = repair(source, placement, plan['gap_um'])
    else:
        metric = pin_objective(source, placement, plan['gap_um'])
        value = dict(placement=deepcopy(placement), initial_metric=metric, metric=metric,
                     pin_evaluations=1, trials=[])
    full, thermal = identities(source, value['placement'], plan['gap_um'])
    routing = screen_metric(value['metric'], source['interposer_width_um'],
                            source['interposer_height_um'], plan['resources'])
    return dict(placement=value['placement'], layout_key=[list(x) for x in full],
                thermal_key=[list(x) for x in thermal], routing=routing,
                pin_length_m=value['metric']['total_pin_manhattan_m'],
                pin_length_um_decimal=value['metric']['total_pin_manhattan_um_decimal'],
                before_pin_length_m=value['initial_metric']['total_pin_manhattan_m'],
                pin_evaluations=value['pin_evaluations'], trials=value['trials'],
                preparation_seconds=time.perf_counter()-started)


def run_arm(source, plan, arm, prepared, warm_rows, warm_thermal, solve):
    """Scan the frozen pool; necessary routing and fixed L cap precede cache/solve.

    All pool entries are scored before heat, including entries beyond the heat
    budget. Cross-arm responses are deliberately not shared in the pilot.
    """
    rows, thermal_records, events = deepcopy(warm_rows), [], []
    cache = {object_hash(r['thermal_key']): (r['thermal_response_id'], warm_thermal[r['thermal_response_id']])
             for r in rows}
    hits = 0
    started = time.perf_counter()
    for candidate, entry in zip(plan['candidates'], prepared, strict=True):
        event = dict(candidate_id=candidate['candidate_id'], **deepcopy(entry))
        events.append(event)
        if not entry['routing']['admitted']:
            event['status'] = 'rejected_necessary_routing'
            continue
        if entry['pin_length_m'] > plan['length_cap_m']:
            event['status'] = 'rejected_length_cap'
            continue
        key = object_hash(entry['thermal_key'])
        if key not in cache and len(thermal_records) >= plan['thermal_budget_per_arm']:
            event['status'] = 'not_evaluated_budget'
            continue
        hit = key in cache
        if not hit:
            data = make_thermal_case(source, entry['placement'], plan['gap_um'], plan['resolution'])
            response = solve(data)
            response_id = f'{arm}/{len(thermal_records)}'
            thermal_records.append(dict(response_id=response_id, candidate_id=candidate['candidate_id'],
                                         thermal_key=deepcopy(entry['thermal_key']),
                                         evaluated_case_sha256=object_hash(data), thermal=response))
            cache[key] = response_id, response
        else:
            hits += 1
        response_id, response = cache[key]
        row = dict(row_index=len(rows), candidate_id=candidate['candidate_id'],
                   placement=deepcopy(entry['placement']), layout_key=entry['layout_key'],
                   thermal_key=entry['thermal_key'], pin_length_m=entry['pin_length_m'],
                   pin_length_um_decimal=entry['pin_length_um_decimal'],
                   peak_c=response['peak_power_layer_c'], thermal_response_id=response_id,
                   thermal_cache_hit=hit, thermal_queries_so_far=len(thermal_records))
        rows.append(row)
        event.update(status='thermal_cache_hit' if hit else 'thermal_evaluated', row_index=row['row_index'])
    return dict(arm=arm, rows=rows, thermal_records=thermal_records, events=events,
                status='complete_thermal_budget' if len(thermal_records) == plan['thermal_budget_per_arm'] else 'exhausted_fixed_pool',
                physical_comparison=profile(rows, plan['length_cap_m'], plan['temperature_cap_c']),
                effort=dict(new_thermal_queries=len(thermal_records), thermal_cache_hits=hits,
                            candidate_pin_evaluations=sum(e['pin_evaluations'] for e in prepared),
                            routing_checks=len(prepared), candidate_count=len(prepared),
                            preparation_seconds=sum(e['preparation_seconds'] for e in prepared),
                            evaluation_seconds=time.perf_counter()-started))
