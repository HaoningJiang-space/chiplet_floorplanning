"""Measure the causal value of hotspot feedback on the temperature-blind native mesh bank."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.package import checked_solution
from chiplet_floorplanning.placement.geometry import is_legal
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from compare_dual_cap_slots import admissible, wire_metrics
from compare_large_pool import (CHECK_LIMIT, RESPONSE_LIMIT, TIE_K, choose, load_bank,
                                point, projected, write_json)
from compare_movable_power import fingerprint
from scale_slot_margin import SEED, SlotPackage
from switch_pool_geometry import instance, workloads


def pool_reference(records):
    """Use only the six common inputs, not thermal information purchased by online methods."""
    clock = perf_counter()
    base, start, bank, pkg, base_field = next(iter(records.values()))
    for _, _, other, package, _ in records.values():
        assert (pkg.a != package.a).nnz == 0 and (pkg.deposit != package.deposit).nnz == 0
        assert np.array_equal(pkg.active, package.active)
        assert np.array_equal(bank.assignments, other.assignments)
    starting_w = np.stack([r[0].power_w for r in records.values()])
    known = (starting_w[1:]-starting_w[0]).T
    known_fields = np.stack([(r[-1]-base_field)[pkg.active] for r in list(records.values())[1:]],axis=1)
    n = base.count
    assert np.allclose(known.sum(axis=0),0.,atol=1e-10) and np.linalg.matrix_rank(known)==known.shape[1]
    # Constant total power removes the all-ones direction. Complete the known differences
    # to a basis using only residual, orthogonal zero-total-power source directions.
    q, _ = np.linalg.qr(np.column_stack((np.ones(n), known)), mode='complete')
    missing = q[:, 1+known.shape[1]:]
    if missing.shape[1] > RESPONSE_LIMIT:
        raise ValueError('insufficient remaining source responses')
    basis = np.column_stack((known,missing))
    fields = [known_fields]
    residuals = []
    for direction in missing.T:
        rhs = pkg.deposit @ direction
        rise = pkg.factor.solve(rhs)
        err, _ = checked_solution(pkg.a,rhs,pkg.sink,rise)
        residuals.append(err)
        fields.append(rise[pkg.active,None])
    response = np.column_stack(fields)
    audit = dict(paid_common_inputs=len(records), known_difference_rank=known.shape[1],
                 extra_source_responses=len(residuals), source_residual_inf_w=max(residuals,default=0.),
                 active_nodes=len(pkg.active), condition=float(np.linalg.cond(basis)), cases={})
    checks = 0
    for name,(p,st,b,_,_) in records.items():
        delta = (b.watts-base.power_w).T
        coeff = np.linalg.lstsq(basis,delta,rcond=None)[0]
        source_error = np.max(abs(delta-basis@coeff)/base.power_w[:,None])
        guard = float(source_error*base_field[pkg.active].max()+1e-8)
        peaks = AMBIENT_C+(base_field[pkg.active,None]+response@coeff).max(axis=0)
        best_id = min(range(len(peaks)),key=lambda i:(peaks[i],b.lengths_m[i],i))
        eligible = np.flatnonzero(peaks<=peaks[0]+TIE_K)
        rev_id = min(eligible,key=lambda i:(b.lengths_m[i],peaks[i],i))
        row = dict(best=point(b,best_id,peaks[best_id]), reverse=point(b,rev_id,peaks[rev_id]),
                   peak_guard_k=guard, source_relative_error=float(source_error), peaks_c=peaks.tolist())
        if name in ('centre_diag','balanced') and best_id!=0:
            layout = Layout(st.centre_um[b.assignments[best_id]],st.rotation_deg)
            assert is_legal(p,layout,100) and admissible(*wire_metrics(p,layout),b.caps)
            s = solve(thermal_case_data(p,layout,100,64),node_limit=450000)[0]
            assert abs(s['peak_power_layer_c']-peaks[best_id]) < guard
            row['independent_check'] = dict(map_id=int(best_id),peak_c=s['peak_power_layer_c'],
                                            balance_error_w=s['energy_balance_error_w'])
            checks += 1
        audit['cases'][name] = row
    assert checks<=CHECK_LIMIT
    audit.update(extra_board_checks=checks, elapsed_s=perf_counter()-clock)
    return audit


def compare(upstream, frozen_path, online_path, truth_path):
    pending = {}
    online = dict(seed=SEED, response_cap=RESPONSE_LIMIT, board_cap=CHECK_LIMIT, cases={})
    modes = ('relation_space_slots','blind','static','single','near')
    t = perf_counter()
    p, start = instance(upstream)
    profiles = workloads(p,start)
    input_s = perf_counter()-t
    for name,watts in profiles.items():
        t = perf_counter()
        problem = replace(p,power_w=watts)
        pkg = SlotPackage(problem,start)
        field = pkg.temperatures(watts)
        start_s = perf_counter()-t
        t = perf_counter()
        frozen, bank = load_bank(frozen_path,p,problem,start)
        assert frozen['cases'][name]['power_w']==watts.tolist()
        load_s = perf_counter()-t
        row = dict(start_c=float(AMBIENT_C+field[pkg.active].max()), start_s=start_s,
                   load_s=load_s, arms={})
        for mode in modes:
            t = perf_counter()
            arm = (projected(problem,start,bank,pkg,field) if mode=='relation_space_slots'
                   else choose(bank,pkg,field,mode,trace_switches=mode in ('static','single','near')))
            arm['decision_s'] = perf_counter()-t
            arm['warm_pool_total_s'] = start_s+arm['decision_s']+(0 if mode=='relation_space_slots' else load_s)
            row['arms'][mode] = arm
        assert row['arms']['single']['candidates'][:2] == row['arms']['static']['candidates'][:2]
        online['cases'][name] = row
        pending[name] = (problem,start,bank,pkg,field)
    online.update(input_s=input_s, pool_sha256=frozen['pool_sha256'], freeze_s=frozen['freeze_s'])
    write_json(online_path,online)
    audit = pool_reference(pending)
    audit['online_sha256'] = fingerprint(online)
    for name,ref in audit['cases'].items():
        peaks = np.array(ref['peaks_c'])
        missed = {}
        for mode,arm in online['cases'][name]['arms'].items():
            for candidate in arm['candidates']:
                assert abs(candidate['peak_c']-peaks[candidate['map_id']]) <= ref['peak_guard_k']
            if 'peak_lower_bounds_c' in arm:
                assert np.max(arm['peak_lower_bounds_c']-peaks) <= ref['peak_guard_k']
            gap = arm['best']['peak_c']-peaks.min()
            assert -TIE_K<=gap<=arm['remaining_bound_k']+TIE_K
            missed[mode] = max(0.,gap)
        ref['missed_k'] = missed
    write_json(truth_path,audit)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('upstream','geometry','online','reference'):
        parser.add_argument('--'+name,required=True,type=Path)
    args = parser.parse_args()
    compare(args.upstream.resolve(),args.geometry,args.online,args.reference)
