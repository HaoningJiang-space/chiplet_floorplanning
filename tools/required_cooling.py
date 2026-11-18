"""Bracket the convection needed for a target, using all-layout bounds and feasible witnesses."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um, solve, thermal_case_data
from compare_heat_floor import sha
from global_heat_floor import trial

TARGET_C = 85.0
WIDTH = 1/64


def exclusion(certificate):
    z = next(i for i,s in enumerate(certificate['stack']) if s['id']=='dies')
    stack = [dict(s, extent_m=tuple(s['extent_m'])) for s in certificate['stack']]
    ambient = certificate['ambient_c']
    powers = certificate['dies']
    total = sum(d['power_w'] for d in powers)
    spatial = []
    if ambient + certificate['carrier_floor_k'] >= TARGET_C+.01:
        spatial.append((None,total))
    sizes = {tuple(d['half_sides_m']) for d in powers if ambient+d['self_floor_k']>=TARGET_C+.01}
    for size in sizes:
        spatial.append((size,max(d['power_w'] for d in powers if tuple(d['half_sides_m'])==size)))
    rows = {1.:certificate['floor_c']}
    if rows[1.] < TARGET_C+.01:
        return dict(factor_lower=1., excluded=False, evaluations=rows)
    def measure(factor):
        h = certificate['h_w_m2k']*factor
        floor = max(p*trial(stack,z,h,size,2)['bound_k_w'] for size,p in spatial)
        rows[factor] = float(np.floor(100*(ambient+floor))/100)
        return rows[factor] >= TARGET_C+.01
    low,high = 1.,32.
    if measure(high):
        low = high
    else:
        while high-low>WIDTH:
            mid = (low+high)/2
            if measure(mid):
                low = mid
            else:
                high = mid
    return dict(factor_lower=low, excluded=True, evaluations=rows)


def search_layout(p, layout, gap_um, previous):
    fields = {res:thermal_case_data(p,layout,gap_um,res) for res in (64,96)}
    h = fields[64]['thermal']['top_h_w_m2k']
    length = float(pin_manhattan_um(p, layout).sum()/1e6)
    assert abs(length-previous['length_m']) < 1e-9
    points = {int(f):dict(peak64_c=previous['observations']['64'][f]['peak_c'],
                          peak96_c=previous['observations']['96'][f]['peak_c'], new=False)
              for f in ('1','2','4','8')}
    def attained(factor):
        if factor not in points:
            row = dict(new=True)
            for res, data in fields.items():
                data['thermal']['top_h_w_m2k'] = h*factor
                metrics,_,_ = solve(data)
                row[f'peak{res}_c'] = metrics['peak_power_layer_c']
                row[f'balance{res}_w'] = metrics['energy_balance_error_w']
            points[factor] = row
        return max(points[factor][k] for k in ('peak64_c','peak96_c')) <= TARGET_C
    low = None
    high = None
    for factor in (1,2,4,8,16,32):
        if attained(factor):
            high = factor
            break
        low = factor
    if high and low:
        while high-low > WIDTH:
            mid = (high+low)/2
            if attained(mid):
                high = mid
            else:
                low = mid
    order = sorted(points)
    for res in (64,96):
        assert all(points[y][f'peak{res}_c'] <= points[x][f'peak{res}_c']+1e-7 for x,y in zip(order,order[1:]))
    return dict(archive_id=previous['archive_id'], length_m=length, factor_upper=high,
                individual_factor_last_miss=low, h_w_m2k=h, evaluations=points)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    evidence = Path(__file__).resolve().parents[1]/'docs/evidence'
    prior = evidence/'global-heat-floor-v1.json'
    prior_sha = sha(prior)
    refs = {r['case']:r for r in json.loads((evidence/'headroom-selection-v1.json').read_text())['records']}
    with ProcessPoolExecutor(args.workers) as pool:
        jobs, pending = {}, {}
        for c in json.loads(prior.read_text())['cases']:
            cert = c['certificate']
            name = cert['case']
            if name.startswith('Case'):
                source = args.data/'physical-calibration/atplace-import-v1'/(name+'.json')
                run = args.data/'rs-grb-v4'/name.lower()
            else:
                source = args.data/'industrial-v1/cases'/(name+'.json')
                run = args.data/'industrial-v1/runs'/name
            assert sha(source)==cert['case_sha256'] and sha(run/'summary.json')==cert['summary_sha256']
            p = Problem.from_imported(json.loads(source.read_text()))
            jobs[name] = dict(case=name, previous_sha256=prior_sha, driver_sha256=sha(Path(__file__)),
                              layouts=[], budgets={}, case_sha256=cert['case_sha256'])
            pending[pool.submit(exclusion,cert)] = (name,'floor')
            with np.load(run/'layouts.npz') as z:
                for record in c['legal_layouts']:
                    i = record['archive_id']
                    layout = Layout(z['centre_um'][i],z['rotation_deg'][i])
                    pending[pool.submit(search_layout,p,layout,refs[name]['gap_um'],record)] = (name,'layout')
        for future in as_completed(pending):
            name,kind = pending[future]
            r = jobs[name]
            answer = future.result()
            if kind=='floor':
                r['necessary'] = answer
            else:
                r['layouts'].append(answer)
            if 'necessary' in r and len(r['layouts']) == len(refs[name]['groups']):
                r['layouts'].sort(key=lambda x:x['archive_id'])
                for g in refs[name]['groups']:
                    cap = g['cap_m']
                    fits = [a for a in r['layouts'] if a['length_m']<=cap+1e-9 and a['factor_upper'] is not None]
                    best = min(fits,key=lambda a:(a['factor_upper'],a['length_m']),default=None)
                    r['budgets'][g['budget']] = dict(cap_m=cap, archive_id=best['archive_id'] if best else None)
                (args.output/(name+'.json')).write_text(json.dumps(r,allow_nan=False)+'\n')
                print(name,flush=True)


if __name__=='__main__':
    main()
