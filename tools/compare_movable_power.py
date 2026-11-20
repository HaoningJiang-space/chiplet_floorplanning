"""Freeze geometric witnesses, then compare budgeted choices on the same double-cap instances."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement.geometry import is_legal
from chiplet_floorplanning.placement.linked_slots import linked_patterns
from chiplet_floorplanning.placement.observer_search import search_observers
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.thermal import AMBIENT_C
from compare_dual_cap_slots import admissible, baseline, point, summary, wire_metrics
from scale_slot_margin import REV, SEED, SlotPackage, problem


CASES = [('folded_torus', 8, 8, w) for w in ('inward', 'outward', 'checker', 'balanced')]
CASES += [('cylinder', 8, 8, 'balanced'), ('mesh', 4, 6, 'balanced')]
CHALLENGES = [('folded_torus', 8, 8, 'inward_ramp'), ('folded_torus', 6, 8, 'balanced_ramp')]
NODE_LIMIT = 5000


def make_case(topology, rows, cols, workload, upstream):
    source = 'folded_torus' if topology == 'cylinder' else topology
    p, start = problem(rows, cols, source, upstream, False, True)
    if topology == 'cylinder':
        mesh, _ = problem(rows, cols, 'mesh', upstream, False, True)
        y = start.centre_um[:, 1]
        horizontal = y[p.pin_chip[:, 0]] == y[p.pin_chip[:, 1]]
        vertical = y[mesh.pin_chip[:, 0]] != y[mesh.pin_chip[:, 1]]
        pins = np.concatenate((p.pin_chip[horizontal], mesh.pin_chip[vertical]))
        offsets = np.concatenate((p.pin_offset_um[horizontal], mesh.pin_offset_um[vertical]))
        p = replace(p, pin_chip=pins, pin_offset_um=offsets)
    # Keep every physical endpoint distinct; work assignments leave the pin graph intact.
    terminals = np.column_stack((p.pin_chip.ravel(), p.pin_offset_um.reshape(-1, 2)))
    assert len(np.unique(terminals, axis=0)) == len(terminals)
    y, x = np.indices((rows, cols))
    base = workload.removesuffix('_ramp')
    if base in ('inward', 'outward'):
        distance = (2*y-rows+1)**2 + (2*x-cols+1)**2
        hot = np.zeros((rows, cols), bool)
        ids = np.arange(p.count).reshape(rows, cols)
        for r in range(0, rows, 2):
            for c in range(0, cols, 2):
                group = ids[r:r+2, c:c+2].ravel()
                closest = np.argsort(distance.ravel()[group], kind='stable')[:2]
                hot.flat[group[closest]] = True
        if base == 'outward':
            hot = ~hot
        hot = hot.ravel()
    elif base == 'checker':
        hot = ((x+y) % 2 == 0).ravel()
    else:
        hot = np.zeros(p.count, bool)
        hot[np.random.default_rng(SEED).permutation(p.count)[:p.count//2]] = True
    power = np.where(hot, p.power_w.max(), p.power_w.min())
    np.testing.assert_allclose(np.sort(power), np.sort(p.power_w), atol=0, rtol=0)
    if workload.endswith('_ramp'):
        power += np.linspace(-.0205, .0205, p.count)
        assert power.min() > 0 and abs(power.sum()-p.power_w.sum()) < 1e-10
    return replace(p, name=f'{topology}_{rows}x{cols}_{workload}', power_w=power), start


def fingerprint(values):
    raw = json.dumps(values, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def geometry(p, start, caps):
    maps, counts = linked_patterns(p, start, *caps, node_limit=NODE_LIMIT)
    i = next(k for k, v in enumerate(maps) if np.array_equal(v.power_w, p.power_w))
    maps.insert(0, maps.pop(i))
    points = []
    for v in maps:
        layout = Layout(start.centre_um[v.chip_to_slot], start.rotation_deg)
        total, longest = wire_metrics(p, layout)
        assert is_legal(p, layout, 100) and admissible(total, longest, caps)
        np.testing.assert_allclose(total, v.wire_m, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(v.power_w[v.chip_to_slot], p.power_w)
        points.append(dict(slot_of_die=v.chip_to_slot.tolist(), hot_slots=np.flatnonzero(
            v.power_w == p.power_w.max()).tolist(), total_m=total, longest_mm=longest))
        if np.unique(p.power_w).size > 2:
            points[-1]['slot_power_w'] = v.power_w.tolist()
    return maps, dict(counts=counts, maps=points)


def slot_arm(p, start, caps, frozen, mode):
    before = perf_counter()
    maps, bank = geometry(p, start, caps)
    assert fingerprint(bank) == frozen['bank_sha256']
    # The fingerprint/geometry checks and any adjoint solves are charged to this arm.
    package = SlotPackage(p, start)
    initial = package.temperatures(p.power_w)
    hot = int(package.active[np.argmax(initial[package.active])])
    peak = float(AMBIENT_C+initial[hot])
    pool = np.stack([v.power_w for v in maps]).T
    checked = [(start, point(p, start, start, peak))]
    if not np.array_equal(maps[0].chip_to_slot, np.arange(p.count)):
        same = Layout(start.centre_um[maps[0].chip_to_slot], start.rotation_deg)
        checked.append((same, point(p, start, same, peak)))
    verified = {0: peak}
    trace = []

    def peak_nodes(field, cell):
        if mode in ('tied_hotspots', 'near_hotspots'):
            window_k = .1 if mode == 'near_hotspots' else 1e-7
            nodes = package.active[field[package.active] >= field[cell] - window_k]
            return tuple(int(node) for node in nodes)
        return (cell,)

    def verify(k):
        v = maps[k]
        field = package.temperatures(v.power_w)
        cell = int(package.active[np.argmax(field[package.active])])
        actual = float(AMBIENT_C+field[cell])
        layout = Layout(start.centre_um[v.chip_to_slot], start.rotation_deg)
        checked.append((layout, point(p, start, layout, actual)))
        verified[k] = actual
        nodes = peak_nodes(field, cell)
        trace.append(dict(map_id=int(k), peak_c=actual, hotspot_node=cell, witness_nodes=list(nodes)))
        return peak-actual, nodes

    def observe(nodes):
        for cell in nodes:
            package.observe(cell)
        response = np.stack([package.rows[cell] for cell in nodes])
        return peak - (AMBIENT_C + np.max(response @ pool, axis=0))

    remaining = None
    initial_floors = final_floors = None
    if mode == 'blind':
        for k in np.random.default_rng(SEED).permutation(np.arange(1, len(maps)))[:2]:
            verify(int(k))
    elif len(maps) > 1:
        upper = observe(peak_nodes(initial, hot))
        if mode == 'per_die':
            for cells in package.slots:
                cell = int(cells[np.argmax(initial[cells])])
                upper = np.minimum(upper, observe((cell,)))
        initial_floors = (peak-upper).tolist()
        result = search_observers(upper, [v.wire_m for v in maps], verify, observe, max_checks=2)
        remaining = result.remaining_gain_bound_k
        floors = np.max(np.stack(list(package.rows.values())) @ pool, axis=0) + AMBIENT_C
        for k, t in verified.items():
            floors[k] = t
        final_floors = floors.tolist()
        assert abs(min(verified.values()) - min(floors) - remaining) <= 2e-7
    else:
        remaining = 0.
    if len(verified) == len(maps):
        remaining = 0.
    selected = summary(p, start, checked, caps)
    selected.update(extra_fv_charged=len(trace), adjoint_rows=len(package.rows),
                    observer_nodes=list(package.rows), trace=trace, bank_sha256=frozen['bank_sha256'],
                    initial_peak_c=peak, initial_floors_c=initial_floors, final_floors_c=final_floors,
                    pool_remaining_k=remaining, all_slots_remaining_k=remaining if bank['counts']['complete'] else None,
                    elapsed_s=perf_counter()-before)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['geometry', 'compare'])
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--geometry', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--challenge', action='store_true')
    args = parser.parse_args()
    up = args.upstream.resolve()
    actual_rev = subprocess.check_output(['git', '-C', str(up), 'rev-parse', 'HEAD'], text=True).strip()
    assert actual_rev == REV
    record = dict(seed=SEED, rapidchiplet=REV, node_limit=NODE_LIMIT, extra_fv_cap=2, cases={})
    path = args.geometry if args.phase == 'geometry' else args.output
    if args.phase == 'compare':
        frozen = json.loads(args.geometry.read_bytes())
        assert frozen['seed'] == SEED and frozen['rapidchiplet'] == REV
        record['geometry_sha256'] = fingerprint(frozen)
        if path is None:
            parser.error('compare requires --output')
    for setup in (CHALLENGES if args.challenge else CASES):
        before = perf_counter()
        p, start = make_case(*setup, up)
        caps = wire_metrics(p, start)
        net_hash = fingerprint([p.pin_chip.tolist(), p.pin_offset_um.tolist(), start.centre_um.tolist(),
                                start.rotation_deg.tolist(), p.size_um.tolist()])
        metadata = dict(graph_sha256=net_hash, power_w=p.power_w.tolist(), cap_m=caps[0],
                        longest_mm=caps[1], net_count=len(p.pin_chip))
        input_s = perf_counter()-before
        if args.phase == 'geometry':
            _, bank = geometry(p, start, caps)
            row = dict(**metadata, **bank, bank_sha256=fingerprint(bank), elapsed_s=perf_counter()-before)
            print(p.name, bank['counts'], flush=True)
        else:
            plan = frozen['cases'][p.name]
            assert all(plan[k] == v for k, v in metadata.items())
            row = dict(input_s=input_s, arms={})
            for mode in ('relation_space_slots','one_hotspot','per_die','blind','relation_space_native',
                         'tied_hotspots','near_hotspots'):
                if mode.startswith('relation_space'):
                    result = baseline(p, start, caps, mode == 'relation_space_slots')
                else:
                    result = slot_arm(p, start, caps, plan, mode)
                result['total_s'] = result['elapsed_s']+input_s
                row['arms'][mode] = result
                print(p.name, mode, round(result['gain_k'],6), round(result['total_s'],3), flush=True)
            starts = [arm['candidates'][0]['peak_c'] for arm in row['arms'].values()]
            assert np.ptp(starts) <= 1e-6
        record['cases'][p.name] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.phase == 'geometry' else 1
    path.write_text(json.dumps(record, indent=indent, allow_nan=False)+'\n', encoding='utf8', newline='\n')


if __name__ == '__main__':
    main()
