"""Freeze a native mesh, six workload references, and its complete dual-cap layout bank."""
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
from large_pool_geometry import inputs, power_maps
from scale_slot_margin import REV, SEED


def instance(upstream):
    revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REV:
        raise ValueError('RapidChiplet revision mismatch')
    p, grid = make_case('mesh', 4, 4, 'balanced_ramp', upstream)
    assignment = np.arange(16)
    for i,j in ((0,1),(6,7),(8,9)):
        assignment[[i,j]] = assignment[[j,i]]
    return p, Layout(grid.centre_um[assignment], grid.rotation_deg)


def workloads(p, start):
    # Specify physical source positions on the starting board, then bind watts to identities.
    x = np.searchsorted(np.unique(start.centre_um[:,0]), start.centre_um[:,0])
    y = np.searchsorted(np.unique(start.centre_um[:,1]), start.centre_um[:,1])
    physical = 4*y+x
    cases = {}
    ramp = np.linspace(-.0205,.0205,p.count)
    for name, pair in [('centre_diag',(5,10)), ('centre_adjacent',(5,6)),
                       ('opposite_edges',(4,11)), ('opposite_corners',(0,15))]:
        hot = np.isin(physical, pair)
        cold_w = (p.power_w.sum()-2*5.125)/(p.count-2)
        cases[name] = np.where(hot,5.125,cold_w)+ramp
    cases['checker'] = np.where((x+y)%2==0,3.075,1.025)+ramp
    cases['balanced'] = p.power_w.copy()
    return cases


def freeze(upstream):
    clock = perf_counter()
    p, start = instance(upstream)
    caps = wire_metrics(p,start)
    pool, counts = linked_patterns(p,start,*caps,node_limit=30000)
    assert counts['complete'] and 300 <= len(pool) <= 3000
    maps = []
    for m in sorted(pool, key=lambda v: tuple(v.chip_to_slot)):
        layout = Layout(start.centre_um[m.chip_to_slot], start.rotation_deg)
        total,longest = wire_metrics(p,layout)
        assert is_legal(p,layout,100) and admissible(total,longest,caps)
        maps.append(dict(slots=m.chip_to_slot.tolist(),total_m=total,longest_mm=longest))
    assignments = np.array([v['slots'] for v in maps])
    assert np.array_equal(assignments[0],np.arange(p.count))
    vectors = workloads(p,start)
    cases = {}
    for name, watts in vectors.items():
        powers = power_maps(watts,assignments)
        rank = int(np.linalg.matrix_rank(powers-powers[0]))
        assert rank > 10 and len(np.unique(powers,axis=0)) == len(maps)
        assert min(watts) > 0 and abs(watts.sum()-p.power_w.sum()) < 1e-10
        cases[name] = dict(power_w=watts.tolist(),rank=rank)
    starts = np.stack(list(vectors.values()))
    return dict(seed=SEED,rapidchiplet=REV,inputs=inputs(p,start),caps=list(caps),counts=counts,
                maps=maps,pool_sha256=fingerprint(maps),cases=cases,
                start_difference_rank=int(np.linalg.matrix_rank(starts-starts[0])),
                freeze_s=perf_counter()-clock)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    bank = freeze(args.upstream.resolve())
    args.output.write_text(json.dumps(bank,allow_nan=False,separators=(',',':'))+'\n',encoding='utf8')
    print(bank['counts'],bank['caps'],bank['start_difference_rank'], bank['pool_sha256'])
    print({k:v['rank'] for k,v in bank['cases'].items()})
