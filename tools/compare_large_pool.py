"""Compare bounded layout selectors on a frozen legal pool, then reveal an independent reference."""
import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.package import checked_solution
from chiplet_floorplanning.placement.evaluate import Evaluator, thermal_key
from chiplet_floorplanning.placement.geometry import is_legal
from chiplet_floorplanning.placement.methods import relation_space
from chiplet_floorplanning.placement.observer_search import search_observers
from chiplet_floorplanning.placement.power_subspace import subspace_peaks
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from compare_dual_cap_slots import ProjectedRun, admissible, wire_metrics
from compare_movable_power import fingerprint
from large_pool_geometry import REV, SEED, inputs, instance, power_maps
from scale_slot_margin import SlotPackage

RESPONSE_LIMIT = 10
CHECK_LIMIT = 2
TIE_K = 1e-7


@dataclass
class Bank:
    assignments: np.ndarray
    watts: np.ndarray
    lengths_m: np.ndarray
    longest_mm: np.ndarray
    caps: tuple


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf8')


def load_bank(path, original, p, start):
    data = json.loads(path.read_bytes())
    assert data['rapidchiplet'] == REV and data['seed'] == SEED
    assert fingerprint(data['maps']) == data['pool_sha256'] and data['inputs'] == inputs(original, start)
    assert tuple(data['caps']) == wire_metrics(p, start) and data['counts']['complete']
    assignments = np.array([v['slots'] for v in data['maps']])
    powers = power_maps(p.power_w, assignments)
    assert np.array_equal(assignments[0], np.arange(p.count))
    assert len(np.unique(powers, axis=0)) == len(assignments)
    bank = Bank(assignments, powers, np.array([v['total_m'] for v in data['maps']]),
                np.array([v['longest_mm'] for v in data['maps']]), tuple(data['caps']))
    return data, bank


def point(bank, k, peak):
    return dict(map_id=int(k), peak_c=float(peak), total_m=float(bank.lengths_m[k]),
                longest_mm=float(bank.longest_mm[k]))


def finish(points, start_peak, remaining, responses, checks):
    best = min(points, key=lambda v: (v['peak_c'], v['total_m'], v['map_id']))
    reverse = min((v for v in points if v['peak_c'] <= start_peak+TIE_K),
                  key=lambda v: (v['total_m'], v['peak_c'], v['map_id']))
    assert responses <= RESPONSE_LIMIT and checks <= CHECK_LIMIT
    return dict(best=best, reverse=reverse, candidates=points, gain_k=start_peak-best['peak_c'],
                remaining_bound_k=remaining if remaining is not None else best['peak_c']-AMBIENT_C,
                responses=responses, candidate_checks=checks)


def projected(p, start, bank, pkg, initial):
    evaluator = Evaluator(p, 100, resolution=64, workers=1)
    peak = AMBIENT_C+initial[pkg.active].max()
    # The start is charged once to the shared input and occupies the original budget slot.
    evaluator.cache[thermal_key(p,start)] = np.r_[peak, [AMBIENT_C+initial[c].max() for c in pkg.slots]]
    evaluator.solves = 1
    run = ProjectedRun(evaluator, start, bank.caps)
    relation_space(run, [start], np.random.default_rng(SEED), milp_s=2., anneal_steps=8,
                   chains=2, batch=6, levels=3, lp_share=1.)
    points = []
    for layout, temp in zip(run.layouts, run.peaks):
        assert is_legal(p, layout, 100) and admissible(*wire_metrics(p, layout), bank.caps)
        slots = (layout.centre_um[:, None, :] == start.centre_um[None, :, :]).all(axis=2).argmax(axis=1)
        idx = np.flatnonzero((bank.assignments == slots).all(axis=1)).item()
        points.append(point(bank, idx, temp))
    checks = evaluator.solves-1
    assert len(evaluator.cache)-1 == checks
    result = finish(points, peak, None, 0, checks)
    result.update(raw_proposals=run.proposals, distinct_projected=len(run.projected),
                  eligible_projected=sum(v['eligible'] for v in run.projected.values()))
    return result


def observer_nodes(pkg, field, owner, single, quota):
    active = pkg.active
    hot = int(active[np.argmax(field[active])])
    if single:
        return (hot,)
    near = active[field[active] >= field[hot]-.1]
    order = near[np.lexsort((near, -field[near]))]
    selected = [hot]
    seen = {owner[hot]}
    room = quota-int(hot not in pkg.rows)
    for separate in (True, False):
        for node in order:
            node = int(node)
            if not room:
                break
            if node in pkg.rows or node in selected or (separate and owner[node] in seen):
                continue
            selected.append(node)
            seen.add(owner[node])
            room -= 1
    return tuple(selected)


def choose(bank, pkg, initial, mode):
    pkg.rows.clear()
    peak = AMBIENT_C+initial[pkg.active].max()
    points = [point(bank, 0, peak)]
    if mode == 'blind':
        for k in np.random.default_rng(SEED).permutation(np.arange(1, len(bank.watts)))[:CHECK_LIMIT]:
            field = pkg.temperatures(bank.watts[k])
            points.append(point(bank, k, AMBIENT_C+field[pkg.active].max()))
        return finish(points, peak, None, 0, len(points)-1)

    owner = np.full(len(initial), -1, dtype=int)
    for idx, cells in enumerate(pkg.slots):
        owner[cells] = idx
    stages = []

    def witnesses(field, quota):
        return observer_nodes(pkg, field, owner, mode == 'single', quota)

    def observe(nodes):
        for node in nodes:
            if node not in pkg.rows and len(pkg.rows) >= RESPONSE_LIMIT:
                raise ValueError('thermal response budget exhausted')
            pkg.observe(node)
        stages.append(list(nodes))
        rows = np.stack([pkg.rows[node] for node in nodes])
        return peak-AMBIENT_C-(rows @ bank.watts.T).max(axis=0)

    def verify(k):
        field = pkg.temperatures(bank.watts[k])
        actual = AMBIENT_C+field[pkg.active].max()
        points.append(point(bank, k, actual))
        return peak-actual, witnesses(field, 3)

    upper = observe(witnesses(initial, 4))
    result = search_observers(upper, bank.lengths_m, verify, observe, max_checks=CHECK_LIMIT)
    floors = AMBIENT_C+(np.stack(list(pkg.rows.values())) @ bank.watts.T).max(axis=0)
    for v in points:
        floors[v['map_id']] = v['peak_c']
    report = finish(points, peak, result.remaining_gain_bound_k, len(pkg.rows), len(points)-1)
    assert abs(report['best']['peak_c']-min(floors)-report['remaining_bound_k']) < 2*TIE_K
    report.update(witnesses_by_stage=stages, peak_lower_bounds_c=floors.tolist())
    return report


def source_reference(p, start, bank, pkg, initial):
    """Recover the action subspace from watts alone; price each signed source separately."""
    active = pkg.active
    residuals = []

    def source_response(direction):
        rhs = pkg.deposit @ direction
        rise = pkg.factor.solve(rhs)
        resid, _ = checked_solution(pkg.a, rhs, pkg.sink, rise)
        residuals.append(resid)
        return rise[active]

    peaks, diagnostics = subspace_peaks(p.power_w, bank.watts, initial[active], source_response, RESPONSE_LIMIT)
    predicted = AMBIENT_C+peaks
    guard = diagnostics['equivalent_peak_guard_k']
    best_id = min(range(len(predicted)), key=lambda i: (predicted[i], bank.lengths_m[i], i))
    start_peak = float(AMBIENT_C+initial[active].max())
    assert abs(start_peak-predicted[0]) <= guard
    # Independently reassemble the selected geometry and its actual power blocks.
    points = [point(bank, 0, start_peak)]
    balance = []
    eligible = np.flatnonzero(predicted <= start_peak+TIE_K)
    rev_id = min(eligible, key=lambda i: (bank.lengths_m[i], predicted[i], i))
    for k in dict.fromkeys([best_id, rev_id]):
        if k == 0:
            continue
        layout = Layout(start.centre_um[bank.assignments[k]], start.rotation_deg)
        assert is_legal(p, layout, 100) and admissible(*wire_metrics(p, layout), bank.caps)
        s = solve(thermal_case_data(p, layout, 100, 64), node_limit=450000)[0]
        assert abs(s['peak_power_layer_c']-predicted[k]) <= guard
        points.append(point(bank, k, s['peak_power_layer_c']))
        balance.append(s['energy_balance_error_w'])
    result = finish(points, start_peak, None, len(residuals), len(points)-1)
    result.update(remaining_bound_k=max(0., result['best']['peak_c']-min(predicted)+guard),
                  **diagnostics, source_residual_inf_w=max(residuals, default=0.), energy_balance_errors_w=balance,
                  optimal_map_id=int(best_id), reverse_id=int(rev_id), pool_peaks_c=predicted.tolist())
    return result


def compare(upstream, geometry, online_path, reference_path):
    pending = []
    output = dict(seed=SEED, response_cap=RESPONSE_LIMIT, new_board_cap=CHECK_LIMIT, cases={})
    for workload in ('balanced', 'complement'):
        clock = perf_counter()
        original, start = instance(upstream)
        watts = original.power_w
        p = original if workload == 'balanced' else replace(original, power_w=2*watts.mean()-watts)
        assert p.power_w.min() > 0 and abs(p.power_w.sum()-watts.sum()) < 1e-10
        pkg = SlotPackage(p, start)
        initial = pkg.temperatures(p.power_w)
        common_s = perf_counter()-clock
        clock = perf_counter()
        frozen, bank = load_bank(geometry, original, p, start)
        load_s = perf_counter()-clock
        row = dict(pool_sha256=frozen['pool_sha256'], start_c=float(AMBIENT_C+initial[pkg.active].max()),
                   common_start_s=common_s, frozen_load_s=load_s, freeze_s=frozen['freeze_s'], arms={})
        for mode in ('relation_space_slots', 'blind', 'single', 'near'):
            clock = perf_counter()
            if mode == 'relation_space_slots':
                result = projected(p, start, bank, pkg, initial)
            else:
                result = choose(bank, pkg, initial, mode)
            result['decision_s'] = perf_counter()-clock
            result['total_s'] = common_s+result['decision_s']+(0 if mode=='relation_space_slots' else load_s)
            row['arms'][mode] = result
        output['cases'][workload] = row
        pending.append((workload, p, start, bank, pkg, initial))
    write_json(online_path, output)

    report = dict(online_sha256=fingerprint(output), cases={})
    for workload, p, start, bank, pkg, initial in pending:
        clock = perf_counter()
        ref = source_reference(p, start, bank, pkg, initial)
        ref['decision_s'] = perf_counter()-clock
        row = output['cases'][workload]
        ref['total_s'] = row['common_start_s']+row['frozen_load_s']+ref['decision_s']
        peaks = np.asarray(ref['pool_peaks_c'])
        ref['missed_k'] = {}
        for mode, arm in row['arms'].items():
            for q in arm['candidates']:
                assert abs(q['peak_c']-peaks[q['map_id']]) <= ref['equivalent_peak_guard_k']
            if 'peak_lower_bounds_c' in arm:
                assert np.max(arm['peak_lower_bounds_c']-peaks) < TIE_K
            miss = arm['best']['peak_c']-peaks.min()
            assert -TIE_K <= miss <= arm['remaining_bound_k']+TIE_K
            ref['missed_k'][mode] = max(0., miss)
        report['cases'][workload] = ref
    write_json(reference_path, report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--geometry', required=True, type=Path)
    parser.add_argument('--online', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    args = parser.parse_args()
    compare(args.upstream.resolve(), args.geometry, args.online, args.reference)
