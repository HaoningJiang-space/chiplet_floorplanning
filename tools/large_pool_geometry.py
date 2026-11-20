"""Build and freeze an exhaustive dual-pin-cap bank without scoring temperatures."""
import argparse
import json
from pathlib import Path
import subprocess
from time import perf_counter

import numpy as np

from compare_movable_power import fingerprint, make_case
from compare_dual_cap_slots import admissible, wire_metrics
from chiplet_floorplanning.placement.geometry import is_legal
from chiplet_floorplanning.placement.linked_slots import linked_patterns
from chiplet_floorplanning.placement.problem import Layout
from scale_slot_margin import REV, SEED


def instance(upstream):
    revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REV:
        raise ValueError(f'expected RapidChiplet {REV}, got {revision}')
    problem, grid = make_case('cylinder', 10, 6, 'balanced_ramp', upstream)
    slots = np.arange(problem.count).reshape(10, 6)
    start_slots = slots.copy()
    start_slots[2::4] = slots[2::4, np.arange(6) ^ 1]
    start_slots[3::4] = slots[3::4, np.arange(6) ^ 1]
    return problem, Layout(grid.centre_um[start_slots.ravel()], grid.rotation_deg)


def inputs(problem, start):
    return dict(pins=problem.pin_chip.tolist(), offsets_um=problem.pin_offset_um.tolist(),
                centres_um=start.centre_um.tolist(), angles_deg=start.rotation_deg.tolist(),
                sizes_um=problem.size_um.tolist(), carrier_um=list(problem.carrier_um),
                power_w=problem.power_w.tolist())


def power_maps(power_w, assignments):
    maps = np.empty(assignments.shape, dtype=float)
    np.put_along_axis(maps, assignments, power_w[None, :], axis=1)
    return maps


def freeze(upstream):
    t = perf_counter()
    p, start = instance(upstream)
    caps = wire_metrics(p, start)
    pool, counts = linked_patterns(p, start, *caps, node_limit=60000)
    pool.sort(key=lambda m: tuple(m.chip_to_slot))
    assert counts['complete'] and len(pool) >= 300
    maps = []
    for m in pool:
        layout = Layout(start.centre_um[m.chip_to_slot], start.rotation_deg)
        total, longest = wire_metrics(p, layout)
        assert admissible(total, longest, caps) and is_legal(p, layout, 100)
        maps.append(dict(slots=m.chip_to_slot.tolist(), total_m=total, longest_mm=longest))
    a = np.array([m['slots'] for m in maps])
    assert np.array_equal(a[0], np.arange(p.count))
    power = power_maps(p.power_w, a)
    assert len(np.unique(power, axis=0)) == len(a)
    return dict(rapidchiplet=REV, seed=SEED, node_cap=60000, inputs=inputs(p,start),
                caps=list(caps), counts=counts, maps=maps, pool_sha256=fingerprint(maps),
                power_difference_rank=int(np.linalg.matrix_rank(power-power[0])),
                freeze_s=perf_counter()-t)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bank = freeze(args.upstream.resolve())
    args.output.write_text(json.dumps(bank, separators=(',', ':'), allow_nan=False)+'\n', encoding='utf8')
    print(bank['counts'], bank['caps'], bank['power_difference_rank'], bank['pool_sha256'])
