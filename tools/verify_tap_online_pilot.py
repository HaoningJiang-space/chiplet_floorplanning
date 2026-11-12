"""Validate saved pilot ledgers and metrics without additional thermal solves."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
from build_tap_ihp_endpoints import source_bytes
from freeze_tap_geometry import verify
from run_tap_online import hashes
from run_tap_online_batch import trial_order
from tap_online import run_policy


def key(placement):
    return tuple((p['id'], p['centre_x_um'], p['centre_y_um'], p['rotation_deg'] % 180)
                 for p in sorted(placement, key=lambda p: p['id']))


def independent_metrics(rows, scale):
    bins = [(round(r['peak_c']/0.000001), round(r['centre_span_mm']/0.000000001)) for r in rows]
    archive = []
    for i, (t, distance) in enumerate(bins):
        if not any(u <= t and v <= distance and (u < t or v < distance) for u, v in bins):
            archive.append(i)
    points = set(((rows[i]['peak_c']-scale['temperature_origin_c'])/scale['temperature_scale_k'],
                  (rows[i]['centre_span_mm']-scale['span_origin_mm'])/scale['span_scale_mm']) for i in archive)
    rx, ry = scale['hypervolume_reference']
    eligible = [(x, y) for x, y in points if x < rx and y < ry]
    # Integrate vertical strips, independently of the online rectangle sweep.
    xs = sorted({x for x, y in eligible} | {rx})
    volume = 0.
    for left, right in zip(xs, xs[1:]):
        bottom = min(y for x, y in eligible if x <= left)
        volume += (right-left)*(ry-bottom)
    return dict(archive_query_indices=archive, hypervolume=volume,
                archive_points_outside_reference=len(points)-len(eligible),
                best_peak_c=min(r['peak_c'] for r in rows),
                best_centre_span_mm=min(r['centre_span_mm'] for r in rows))


def check_metrics(actual, expected):
    for name, value in expected.items():
        if isinstance(value, float):
            if not math.isclose(actual[name], value, rel_tol=1e-11, abs_tol=1e-11):
                raise ValueError('Metric mismatch: '+name)
        elif actual[name] != value:
            raise ValueError('Metric mismatch: '+name)


def validate_run(result, entry, plan, replay=False):
    domain = entry['domain']
    seed = result['seed']
    initial = next(i['placements'] for i in entry['initializations'] if i['seed'] == seed)
    rows = result['rows']
    if result['smoke_only'] or result['budget'] != plan['budget'] or result['scale'] != entry['scale']:
        raise ValueError('Smoke, budget or scale mismatch')
    if result['search_seed'] != seed+1000000 or result['hits_commit'] != plan['hits_commit']:
        raise ValueError('RNG or solver source mismatch')
    if result['queries'] != len(rows) or result['solve_attempts'] != len(rows):
        raise ValueError('Query/attempt count mismatch')
    for field in ('elapsed_seconds', 'solve_seconds', 'geometry_seconds'):
        if not math.isfinite(result[field]) or result[field] < 0:
            raise ValueError('Invalid elapsed-time evidence')
    if result['solve_seconds']+result['geometry_seconds'] > result['elapsed_seconds']+1e-8:
        raise ValueError('Measured subcosts exceed total time')
    if len(rows) < 16 or [r['placement'] for r in rows[:16]] != initial:
        raise ValueError('Shared initialization not fully charged')
    if result['status'] == 'complete_query_budget':
        if len(rows) != plan['budget']:
            raise ValueError('False completion')
    elif result['status'] == 'stopped_at_limit':
        capped = result['reason'] == 'proposal_cap' and result['proposals'] == plan['proposal_cap']
        exhausted = result['method'] == 'tap_sa' and result['reason'] == 'all one-grid-step moves rejected; global feasibility unknown'
        if not (capped or exhausted) or len(rows) >= plan['budget']:
            raise ValueError('Invalid cap status')
    else:
        raise ValueError('Failed/unknown run must be reported separately, not compared')
    expected_power = sum(c['power_w'] for c in domain['chiplets'])
    demands = domain['connection_wire_demands']
    total_demand = sum(map(sum, demands))
    seen = {}
    for i, row in enumerate(rows):
        verify(domain, row['placement'])
        state = key(row['placement'])
        if row['query_index'] != i or state in seen:
            raise ValueError('Duplicate or misindexed thermal query')
        seen[state] = i
        by_id = {p['id']: p for p in row['placement']}
        weighted = sum(demands[a][b]*(abs(by_id[a]['centre_x_um']-by_id[b]['centre_x_um'])+
                                     abs(by_id[a]['centre_y_um']-by_id[b]['centre_y_um']))
                       for a in range(len(demands)) for b in range(len(demands)))
        if not math.isclose(row['centre_span_mm'], weighted/(1000*total_demand), abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError('Centre span mismatch')
        t = row['thermal']
        finite_keys = ('peak_power_layer_c', 'source_power_w', 'mapped_power_w', 'heat_removed_w',
                       'energy_balance_error_w', 'original_relative_residual', 'max_reference_difference_k',
                       'min_rise_k', 'max_internal_coefficient_change_w_k', 'max_asymmetry_w_k', 'max_offdiagonal_w_k')
        if not all(math.isfinite(t[k]) for k in finite_keys):
            raise ValueError('Nonfinite thermal evidence')
        if not (t['numerical_admission_passed'] and t['hits_receipt']['accepted']
                and abs(t['source_power_w']-expected_power) < 1e-7
                and abs(t['mapped_power_w']-expected_power) < 1e-7
                and abs(t['heat_removed_w']-expected_power) <= 1e-4
                and abs(t['energy_balance_error_w']) <= 1e-4
                and t['original_relative_residual'] <= 1e-8
                and t['max_reference_difference_k'] <= 1e-3
                and t['min_rise_k'] >= -1e-8
                and t['max_internal_coefficient_change_w_k'] == 0
                and t['max_asymmetry_w_k'] == 0 and t['max_offdiagonal_w_k'] <= 0
                and row['peak_c'] == t['peak_power_layer_c']):
            raise ValueError('Thermal evidence violates the frozen checks')
    observed = {}
    counts = Counter()
    for number, event in enumerate(result['events'], start=1):
        if event['proposal'] != number:
            raise ValueError('Proposal sequence mismatch')
        status = event['status']
        counts[status] += 1
        placement = event['placement']
        if status == 'geometry_rejected':
            if placement is not None:
                try:
                    verify(domain, placement)
                except ValueError:
                    pass
                else:
                    raise ValueError('Legal geometry marked rejected')
            continue
        verify(domain, placement)
        state = key(placement)
        if status == 'thermal_evaluated':
            index = len(observed)
            if state in observed or event['query_index'] != index or rows[index]['placement'] != placement:
                raise ValueError('Query event does not match saved row')
            observed[state] = index
        elif status == 'cache_hit':
            if state not in observed or event['query_index'] != observed[state]:
                raise ValueError('Cache hit references an unseen or wrong state')
        else:
            raise ValueError('Unexpected event in a terminal complete/capped run')
    if (result['proposals'] != len(result['events']) or counts['thermal_evaluated'] != len(rows)
            or counts['cache_hit'] != result['cache_hits'] or counts['geometry_rejected'] != result['illegal_proposals']):
        raise ValueError('Event count mismatch')
    expected_checkpoints = [n for n in (16, 32, 64) if n <= len(rows)]
    if [c['queries'] for c in result['checkpoints']] != expected_checkpoints:
        raise ValueError('Missing or unexpected checkpoints')
    for checkpoint in result['checkpoints']:
        count = checkpoint['queries']
        check_metrics(checkpoint, independent_metrics(rows[:count], entry['scale']))
        query_event = next(e for e in result['events'] if e['status'] == 'thermal_evaluated' and e['query_index'] == count-1)
        if checkpoint['proposals'] != query_event['proposal']:
            raise ValueError('Checkpoint proposal count mismatch')
    times = [c['elapsed_seconds'] for c in result['checkpoints']]
    if times != sorted(times) or any(not math.isfinite(t) or not 0 <= t <= result['elapsed_seconds'] for t in times):
        raise ValueError('Invalid checkpoint timing')
    check_metrics(result['final_metrics'], independent_metrics(rows, entry['scale']))
    if 'comparison' in entry:
        from tap_r3_metrics import summarize
        if result['research_metrics'] != summarize(result, entry['scale'], entry['comparison']):
            raise ValueError('Physical comparison or effort metrics mismatch')
    if replay:
        def lookup(placement):
            # Reject any unseen state instead of allowing uncharged oracle access.
            return rows[seen[key(placement)]]['thermal']
        kwargs = dict(budget=plan['budget'], proposal_cap=plan['proposal_cap'], comparison=entry.get('comparison'))
        if result['method'] == 'tap_sa':
            from tap_published_moves import run_tap_policy
            replayed = run_tap_policy(domain, initial, entry['scale'], seed, lookup, **kwargs)
        else:
            replayed = run_policy(domain, initial, entry['scale'], result['method'], seed, lookup, **kwargs)
        fields = ['status', 'reason', 'queries', 'solve_attempts', 'proposals', 'illegal_proposals',
                  'cache_hits', 'generations', 'events', 'construction_candidate_checks']
        if result['method'] == 'tap_sa':
            fields.append('decisions')
        if result['method'] == 'nsga2_legal':
            fields += ['mutation_candidate_checks', 'empty_mutation_sets']
        for field in fields:
            if replayed[field] != result[field]:
                raise ValueError('Policy replay mismatch: '+field)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    raw_plan = source_bytes(args.plan)
    plan = json.loads(raw_plan)
    if hashes() != plan['source_sha256']:
        raise ValueError('Current frozen implementation no longer matches')
    batch = json.loads((args.root/'batch.json').read_text(encoding='utf-8'))
    if batch['runs'] != trial_order(plan) or batch['plan_sha256'] != hashlib.sha256(raw_plan).hexdigest():
        raise ValueError('Batch order or plan mismatch')
    if not args.partial and (batch['status'] not in ('complete', 'complete_with_caps') or len(batch['completed']) != 45):
        raise ValueError('Batch not complete; use --partial only for diagnostic verification')
    records = []
    for index, completed in enumerate(batch['completed']):
        trial = batch['runs'][index]
        if any(completed[k] != trial[k] for k in trial):
            raise ValueError('Batch completion order mismatch')
        path = args.root/f"{trial['case']}-{trial['seed']}-{trial['method']}"/'result.json'
        raw = source_bytes(path)
        result = json.loads(raw)
        if result['plan_sha256'] != batch['plan_sha256'] or any(result[k] != v for k, v in trial.items()):
            raise ValueError('Trial identity or manifest mismatch')
        if any(result[k] != completed[k] for k in ('status', 'queries', 'reason')):
            raise ValueError('Batch completion record disagrees with trial')
        entry = next(c for c in plan['cases'] if c['domain']['name'] == trial['case'])
        validate_run(result, entry, plan, args.replay)
        record = {k: result[k] for k in ('case', 'method', 'seed', 'status', 'reason', 'queries',
                    'proposals', 'cache_hits', 'illegal_proposals', 'generations', 'solve_seconds',
                    'geometry_seconds', 'elapsed_seconds', 'construction_candidate_checks', 'checkpoints', 'final_metrics')}
        record['raw_result_sha256'] = hashlib.sha256(raw).hexdigest()
        record['points'] = [dict(query_index=r['query_index'], placement=r['placement'], peak_c=r['peak_c'],
                                 centre_span_mm=r['centre_span_mm']) for r in result['rows']]
        records.append(record)
    result = dict(status='partial_verification_not_comparative' if args.partial else 'complete_pilot_verified',
                  batch_status=batch['status'], verified_runs=len(records), expected_runs=45,
                  plan_sha256=batch['plan_sha256'], code_commit=batch['commit'],
                  policy_replay=args.replay, records=records, summaries=[])
    if not args.partial:
        for entry in plan['cases']:
            for method in ('random', 'sa', 'nsga2'):
                group = [r for r in records if r['case'] == entry['domain']['name'] and r['method'] == method]
                result['summaries'].append(dict(case=entry['domain']['name'], method=method,
                    completed=sum(r['status'] == 'complete_query_budget' for r in group),
                    capped=sum(r['status'] == 'stopped_at_limit' for r in group),
                    median_final_hypervolume=statistics.median(r['final_metrics']['hypervolume'] for r in group),
                    median_elapsed_seconds=statistics.median(r['elapsed_seconds'] for r in group),
                    median_proposals=statistics.median(r['proposals'] for r in group)))
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, indent=2))


if __name__ == '__main__':
    main()
