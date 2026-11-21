"""Look for counterexamples in already measured fields and in geometry-only feasibility."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Layout
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from chiplet_floorplanning.placement.successors import follower_landing, joint_endpoints, proxy_peaks
from compare_large_pool import write_json
from compare_successors import audit, load_case


def omitted_hotspots(p,start,case):
    three = case['arms']['three']
    obs = list(dict.fromkeys([int(np.argmax(case['start']['die_peaks_c'])),*three['replacement_order']]))[:3]
    start_die = np.array(case['start']['die_peaks_c'])
    tested = {}
    for name,arm in case['arms'].items():
        for index,row in enumerate(arm['verified']):
            pose = Layout(np.array(row['centre_um'],dtype=float),np.array(row['rotation_deg'],dtype=int))
            identity = (pose.centre_um.tobytes(),pose.rotation_deg.tobytes())
            ref = f'{name}/{index}'
            if identity in tested:
                tested[identity]['seen_in'].append(ref)
                continue
            die = np.asarray(row['die_peaks_c'])
            limited = float(die[obs].max())
            tested[identity] = dict(seen_in=[ref],true_c=row['peak_c'],true_hot=p.names[int(np.argmax(die))],
                                    observed_c=limited,omitted_k=max(0.,row['peak_c']-limited),
                                    proxy_c=float(max(proxy_peaks(p,start,pose,start_die,obs))))
    rows = list(tested.values())
    inverted, proxy_inverted = [], []
    for i,row in enumerate(rows):
        for j,other in enumerate(rows[:i]):
            true_delta = row['true_c'] - other['true_c']
            observed_delta = row['observed_c'] - other['observed_c']
            if min(abs(true_delta),abs(observed_delta)) > 1e-7 and true_delta*observed_delta < 0:
                inverted.append(dict(i=i,j=j,true_delta_k=true_delta,observed_delta_k=observed_delta))
            proxy_delta = row['proxy_c'] - other['proxy_c']
            if min(abs(true_delta),abs(proxy_delta)) > 1e-7 and true_delta*proxy_delta < 0:
                proxy_inverted.append(dict(i=i,j=j,true_delta_k=true_delta,proxy_delta_k=proxy_delta))
    return dict(observers=[p.names[i] for i in obs],endpoints=rows,rank_inversions=inverted,
                proxy_rank_inversions=proxy_inverted)


def unlocked_witnesses(p,start,reach,cap,arm):
    cell = PinReachCell(p,start,100,reach,cap)
    witnesses = []
    for row in arm['attempts']:
        if row['candidate'] is not None:
            continue
        leader = row['leader']
        step = np.array(row['step_mm'])
        forced = set(row['followers'])
        # A duplicate in the original bank is not a geometry miss.
        locked = follower_landing(cell,start,leader,step,forced,arm['radius_mm'])
        if locked is not None:
            continue
        alternative = follower_landing(cell,start,leader,step,set(range(p.count)),arm['radius_mm'])
        if alternative is None:
            continue
        admitted = audit(p,alternative,reach,cap)
        if not admitted['admitted']:
            continue
        delta = (alternative.centre_um-start.centre_um)/1000
        moved = set(np.flatnonzero(abs(delta).max(axis=1)>1e-7).tolist())
        if not (moved-forced-{leader}):
            continue
        solo = start.centre_um.copy()
        solo[leader] += 1000*step
        solo_metrics = audit(p,Layout(solo,start.rotation_deg),reach,cap)
        witnesses.append(dict(leader=p.names[leader],step_mm=row['step_mm'],certified=[p.names[i] for i in sorted(forced)],
                              additionally_moved=[p.names[i] for i in sorted(moved-forced-{leader})],
                              solo_wire_m=solo_metrics['wire_m'],solo_admitted=solo_metrics['admitted'],
                              alternative=admitted))
    return witnesses


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('source','results','compensated','output'):
        parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    raw = args.results.read_bytes()
    data=json.loads(raw)
    second=json.loads(args.compensated.read_bytes())
    assert sha256(raw.replace(b'\r\n',b'\n')).hexdigest()==second['first_stage_sha256']
    out={}
    for name,case in data['cases'].items():
        t=perf_counter()
        p,start,reach,cap,_=load_case(name,args.source)
        a,b=case['arms']['three'],case['arms']['all']
        assert a['bank']==b['bank'] and a['eligible']==b['eligible']
        # Rebuild the frozen strict bank using the final grid and motion checks.
        _, strict, _ = joint_endpoints(p,start,reach,cap,np.array(case['start']['die_peaks_c']))
        assert [audit(p,pose,reach,cap) for pose in strict]==a['bank']
        newer=second['cases'][name]
        assert newer['start']==case['start'] and newer['source_sha256']==case['source_sha256']
        expanded,full=newer['arms']['three'],newer['arms']['all']
        assert expanded['bank']==full['bank'] and expanded['eligible']==full['eligible']
        case['arms'].update(compensated_three=expanded,compensated_all=full)
        for arm in case['arms'].values():
            assert arm['new_board_checks']<=2
            for row in arm['verified']:
                checked=audit(p,Layout(np.array(row['centre_um']),np.array(row['rotation_deg'])),reach,cap)
                assert checked['admitted'] and abs(checked['wire_m']-row['wire_m'])<1e-10
        out[name]=dict(thermal=omitted_hotspots(p,start,case),
                       unlocked=unlocked_witnesses(p,start,reach,cap,a),
                       observed_miss_vs_all_k=max(0.,a['peak_c']-b['peak_c']),
                       observed_miss_vs_any_k=a['peak_c']-min(r['peak_c'] for r in case['arms'].values()),
                       compensated_miss_vs_all_k=max(0.,expanded['peak_c']-full['peak_c']),
                       compensated_miss_vs_any_k=expanded['peak_c']-min(r['peak_c'] for r in case['arms'].values()),
                       new_board_checks=0,seconds=perf_counter()-t)
    write_json(args.output,out)


if __name__=='__main__':
    main()
