"""Compare certified follower moves, sparse/all-die selection and two placement baselines."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Evaluator, Layout, Problem
from chiplet_floorplanning.placement.evaluate import thermal_key
from chiplet_floorplanning.placement.methods import Run, relation_space
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from chiplet_floorplanning.placement.successors import joint_endpoints, proxy_peaks, successor_order
from compare_continuous_reach import point, verified
from compare_large_pool import write_json
from continuous_baseline_audit import escape_util
from import_atplace_cases import parse_case


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence'
SEED = 20261119


def load_case(name, source):
    frozen = json.loads((EVIDENCE/'successor-freeze.json').read_bytes())
    if name in ('Stagger12','Stagger12P'):
        rec = (frozen['holdout'] if name=='Stagger12'
               else json.loads((EVIDENCE/'successor-distinct-pins.json').read_bytes()))
        raw = {}
        for ext, digest in rec['files_sha256'].items():
            data = (ROOT/'examples'/name/f'{name}.{ext}').read_bytes().replace(b'\r\n',b'\n')
            assert sha256(data).hexdigest() == digest
            raw[ext] = data.decode()
        data = parse_case(name, raw['blocks'], raw['power'], raw['nets'])
        data['power_provenance'] = 'declared synthetic held-out workload'
        encoded = json.dumps(data, separators=(',',':')).encode()
        start = Layout(np.array(rec['start_um'],float),np.array(rec['angles'],int))
    else:
        geom = (EVIDENCE/'continuous-reach-geometry.json').read_bytes()
        # The historical JSON may have been checked out with Windows CRLF.
        lf = geom.replace(b'\r\n',b'\n')
        assert frozen['legacy_geometry_sha256'] in {
            sha256(s).hexdigest() for s in (lf, lf.replace(b'\n',b'\r\n'))}
        rec = json.loads(geom)['cases'][name]
        encoded = (source/f'{name}.json').read_bytes()
        assert sha256(encoded).hexdigest() == rec['source_sha256']
        st = rec['start']
        start = Layout(np.array(st['centre_um'],float),np.array(st['rotation_deg'],int))
    return Problem.from_imported(json.loads(encoded)), start, np.array(rec['reach_mm']), rec['cap_m'], encoded


def audit(p, pose, reach, cap):
    row = point(p,pose,reach,cap)
    row['bin_escape_utilization'] = escape_util(p,pose)
    row['admitted'] = bool(row['feasible'] and row['bin_escape_utilization'] <= 1.)
    return row


def measure(p, pose, row):
    summary, peaks = verified(p,pose)
    return dict(row, peak_c=summary['peak_power_layer_c'], die_peaks_c=peaks.tolist(),
                balance_w=summary['energy_balance_error_w'])


def shared_repair(p, pose, cell, reach, cap):
    original = audit(p,pose,reach,cap)
    if original['admitted']:
        return pose, original, 'raw'
    fixed = cell.toward(pose.centre_um)
    if fixed is not None and audit(p,fixed,reach,cap)['admitted']:
        return fixed, original, 'projected'
    return None, original, 'rejected'


def result(rows, base, checks):
    eligible = [row for row in rows if row['admitted']]
    best = min(eligible,key=lambda row:(row['peak_c'],row['wire_m']))
    reverse = min(row['wire_m'] for row in eligible if row['peak_c'] <= base['peak_c']+1e-7)
    return dict(verified=rows, peak_c=best['peak_c'], wire_m=best['wire_m'],
                cooling_k=base['peak_c']-best['peak_c'], reverse_m=reverse, new_board_checks=checks)


def follower_arm(p, start, reach, cap, base, all_dies, compensate=False):
    peaks = np.array(base['die_peaks_c'])
    radius, poses, attempts = joint_endpoints(p,start,reach,cap,peaks,compensate=compensate)
    geometry = [audit(p,v,reach,cap) for v in poses]
    eligible = [i for i,g in enumerate(geometry) if g['admitted']]
    risk = successor_order(p,start,peaks,radius)
    hottest = int(np.argmax(peaks))
    observed = [hottest, *risk]
    rows, decisions = [base], []
    pool = list(eligible)
    for _ in range(2):
        if not pool:
            break
        obs = list(range(p.count)) if all_dies else list(dict.fromkeys(observed))[:3]
        predicted = {i:float(max(proxy_peaks(p,start,poses[i],peaks,obs))) for i in pool}
        take = min(pool,key=lambda i:(predicted[i], geometry[i]['wire_m'], i))
        pool.remove(take)
        row = measure(p,poses[take],geometry[take])
        actual = np.array(row['die_peaks_c'])
        hot = int(np.argmax(actual))
        rows.append(dict(row,candidate=take))
        decisions.append(dict(observers=obs,selected=take,predicted_peaks=predicted,
                              actual_hot=hot,hot_omitted=hot not in obs,
                              unobserved_excess_k=max(0.,row['peak_c']-float(max(actual[obs])))))
        observed = [hottest, hot, *risk]
    return dict(result(rows,base,len(rows)-1), attempts=attempts, bank=geometry, eligible=eligible,
                replacement_order=risk, radius_mm=radius, decisions=decisions, reduced_labels=0)


class ProjectedRun(Run):
    """Use the native proposal flow with the common admission/projection before each costly check."""
    def __init__(self, evaluator, start, reach, cap):
        super().__init__(evaluator,3,stall_rounds=2,max_rounds=3)
        self.cell = PinReachCell(evaluator.problem,start,100,reach,cap)
        self.reach, self.cap, self.raw = reach, cap, []

    def evaluate(self, candidates):
        indices = []
        for pose in candidates:
            if self.exhausted:
                indices.append(None)
                continue
            chosen, raw, mode = shared_repair(self.evaluator.problem,pose,self.cell,self.reach,self.cap)
            self.raw.append(dict(source=raw,handling=mode))
            indices.append(super().evaluate([chosen])[0] if chosen is not None else None)
        return indices


def relation_arm(p,start,reach,cap,base):
    with Evaluator(p,100,resolution=64) as evaluator:
        evaluator.cache[thermal_key(p,start)] = np.r_[base['peak_c'],base['die_peaks_c']]
        evaluator.solves = 1
        run = ProjectedRun(evaluator,start,reach,cap)
        relation_space(run,[start],np.random.default_rng(SEED),milp_s=2.,anneal_steps=8,
                       chains=2,batch=6,levels=3,lp_share=1.,caps=0)
        rows = [dict(audit(p,pose,reach,cap),peak_c=float(temp),die_peaks_c=die.tolist())
                for pose,temp,die in zip(run.layouts,run.peaks,run.die_peaks)]
        assert all(row['admitted'] for row in rows) and evaluator.solves<=3
        return dict(result(rows,base,evaluator.solves-1), proposals=run.raw,reduced_labels=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--atpython',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',default=('Case7','Case8','Stagger12'),
                        choices=('Case7','Case8','Stagger12','Stagger12P'))
    parser.add_argument('--compensate-from',type=Path,
                        help='Run the second-stage pair from the same measured starting fields.')
    args=parser.parse_args()
    from successor_atplace import external_arm
    out = dict(seed=SEED,cases={})
    if args.compensate_from:
        raw = args.compensate_from.read_bytes()
        initial = json.loads(raw)
        out['first_stage_sha256'] = sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
    for name in args.cases:
        t = perf_counter()
        p,start,reach,cap,encoded = load_case(name,args.source)
        geom = audit(p,start,reach,cap)
        assert geom['admitted']
        if args.compensate_from:
            prev = initial['cases'][name]
            assert (prev['source_sha256']==sha256(encoded).hexdigest() and prev['cap_m']==cap
                    and prev['start']['centre_um']==geom['centre_um']
                    and prev['start']['rotation_deg']==geom['rotation_deg'])
            base, common = prev['start'],prev['common_s']
        else:
            base = measure(p,start,geom)
            common = perf_counter()-t
        case = dict(source_sha256=sha256(encoded).hexdigest(),names=p.names,start=base,
                    cap_m=cap,reach_classes_mm=np.unique(reach).tolist(),common_s=common,arms={})
        out['cases'][name]=case
        methods = ('three','all') if args.compensate_from else ('three','all','relation_space','ATPlace2.5D')
        for arm in methods:
            t = perf_counter()
            if arm in ('three','all'):
                record = follower_arm(p,start,reach,cap,base,arm=='all',compensate=bool(args.compensate_from))
            elif arm=='relation_space':
                record = relation_arm(p,start,reach,cap,base)
            else:
                record = external_arm(p,start,reach,cap,base,encoded,args)
            record['total_s'] = common+perf_counter()-t
            assert record['new_board_checks']<=2 and record['reduced_labels']<=5
            case['arms'][arm]=record
            write_json(args.output,out)
            print(name,arm,'peak',record['peak_c'],'checks',record['new_board_checks'],
                  'seconds',round(record['total_s'],3),flush=True)


if __name__=='__main__':
    main()
