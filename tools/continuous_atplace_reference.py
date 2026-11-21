"""Run the published ATPlace optimizer locally with five separately charged reduced labels."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np

from atplace_compare import from_atplace
from compare_atplace_margin import problem_at, write
from continuous_metrics import escape_util, inspect
from continuous_reach_geometry import NAMES, PIN
from evidence_io import write_json
from chiplet_floorplanning.placement.evaluate import sample_legal
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.thermal import thermal_case_data, solve
from chiplet_floorplanning.placement.thermal_projection import projected_field


def sample(out):
    _,p,_ = problem_at(out)
    rng = np.random.default_rng(20261119)
    result = []
    for _ in range(5):
        layout = sample_legal(p,101,rng)
        sizes = np.where((layout.rotation_deg%180!=0)[:,None],p.size_um[:,::-1],p.size_um)
        result.append(np.c_[layout.centre_um,sizes])
    np.savez(out/'fallback-samples.npz',names=p.names,geometry=np.array(result,dtype=np.float32))


def labels(out):
    _,p,_ = problem_at(out)
    sample = np.load(out/'sampled.npz')
    order = [sample['names'].tolist().index(n) for n in p.names]
    nx,ny = sample['grid']
    w,h = np.array(p.carrier_um)/1000
    xs = (200-w)/2+(np.arange(nx)+.5)*w/nx
    ys = (200-h)/2+(np.arange(ny)+.5)*h/ny
    fields = []
    for geom in sample['geometry']:
        g = geom[order]
        angles = np.where(np.isclose(g[:,2],p.size_um[:,0]),0,90)
        _,rise,(ex,ey) = projected_field(p,Layout(g[:,:2],angles))
        fields.append(rise[np.ix_(np.searchsorted(ey,ys,side='right')-1,
                                  np.searchsorted(ex,xs,side='right')-1)].T)
    assert np.isfinite(fields).all()
    np.save(out/'labels.npy',fields)


def log_outcome(path):
    lines=path.read_text(encoding='utf8',errors='replace')
    return dict(initialization_missed='!Initial solution not found!' in lines,
                weighted_legalization_missed='WL legalization returned no result' in lines,
                displacement_export='!Legalized Floorplan of  Dis  found!' in lines)


def audit_result(report, rec, p, sub):
    start=rec['start']
    accepted=[dict(peak_c=report['start_peak_c'],wire_m=start['wire_m'],origin='common start')]
    endpoint=report.get('endpoint')
    if endpoint:
        pose=Layout(np.array(endpoint['centre_um']),np.array(endpoint['rotation_deg']))
        endpoint['bin_escape_utilization']=escape_util(p,pose)
        if endpoint['feasible'] and endpoint['bin_escape_utilization']<=1.:
            accepted.append(dict(peak_c=endpoint['peak_c'],wire_m=endpoint['wire_m'],origin='native export'))
    report['best']=min(accepted,key=lambda r:(r['peak_c'],r['wire_m']))
    report['reverse_m']=min(r['wire_m'] for r in accepted if r['peak_c']<=report['start_peak_c']+1e-7)
    report['cold_with_geometry_s']=report['cold_s']+rec['geometry_s']
    for name,stage in report['stages'].items():
        if name.startswith('native-'):
            stage.update(log_outcome(sub/(name+'.log')))
        if stage['exit']:
            lines=(sub/(name+'.log')).read_text(encoding='utf8',errors='replace').splitlines()
            stage['failure']=next((line for line in reversed(lines) if line.strip()),'no log message')
    if (sub/'labels.npy').exists():
        report['reduced_responses']=len(np.load(sub/'labels.npy',mmap_mode='r'))


def run(args):
    protocol = json.loads(args.geometry.read_bytes())
    assert subprocess.check_output(['git','-C',str(args.upstream),'rev-parse','HEAD'],text=True).strip()==PIN
    results={}
    for name in NAMES:
        rec=protocol['cases'][name]
        if not rec['start']:
            results[name]=dict(status='no admissible start',new_board_checks=0)
            continue
        then=perf_counter()
        sub=args.work/name
        sub.mkdir(parents=True,exist_ok=True)
        raw=(args.source/(name+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==rec['source_sha256']
        (sub/'source.json').write_bytes(raw)
        data=json.loads(raw)
        start=rec['start']
        write(sub/'input.json',dict(name=name,cap_m=rec['cap_m'],source_sha256=rec['source_sha256'],
              start_um=start['centre_um'],angles=start['rotation_deg'],names=rec['die_names'],
              powers_w=[float(c['power_w_decimal']) for c in data['chiplets']],upstream=PIN,
              fv_fingerprint=sha256(Path(sys.modules[projected_field.__module__].__file__).read_bytes()).hexdigest()))
        _,p,anchor=problem_at(sub)
        report = dict(status='running', stages={},new_board_checks=0,reduced_responses=0)
        results[name]=report
        for phase,limit in [('train',10.),('native',10.),('native',30.)]:
            if phase=='native' and report.get('exported'):
                break
            t=perf_counter()
            label=phase+'-'+str(int(limit))
            with (sub/(label+'.log')).open('w',encoding='utf8') as log:
                proc=subprocess.run([str(args.atpython.resolve()),str(Path(__file__).with_name('atplace_shared_fv.py')),
                        str(args.upstream.resolve()),str(sub.resolve()),phase,sys.executable,
                        '--projected-labels','--native-limit-s',str(limit)],stdout=log,stderr=subprocess.STDOUT)
            report['stages'][label] = dict(seconds=perf_counter()-t,exit=proc.returncode)
            if phase=='train':
                if proc.returncode:
                    report['status']='training failed'
                    break
                report['training']=json.loads((sub/'training.json').read_bytes())
                report['reduced_responses']=5
            elif not proc.returncode:
                report['exported']=True
                row=json.loads((sub/'native.json').read_bytes())
                proposal=from_atplace(p,row)
                metrics=inspect(p,proposal,np.array(rec['reach_mm']),rec['cap_m'])
                report['endpoint']=dict(**metrics,centre_um=proposal.centre_um.tolist(),
                                        rotation_deg=proposal.rotation_deg.tolist())
                if metrics['legal']:
                    summary=solve(thermal_case_data(p,proposal,100,64))[0]
                    report['endpoint']['peak_c']=summary['peak_power_layer_c']
                    report['new_board_checks']=1
                report['status']='exported'
        if report['status']=='running':
            report['status']='native optimizer failed'
        report['start_peak_c']=solve(thermal_case_data(p,anchor,100,64))[0]['peak_power_layer_c']
        report['cold_s']=perf_counter()-then
        audit_result(report,rec,p,sub)
        write_json(args.output,results)
        print(name,report['status'],report['cold_s'],flush=True)


def warm(args):
    """Recover the author's thermal optimization if neither initialization supplied a position."""
    geometric=json.loads(args.geometry.read_bytes())['cases']
    original=json.loads(args.external.read_bytes())
    records={}
    for name,report in original.items():
        if 'start_peak_c' not in report or report.get('endpoint') or not report.get('training'):
            continue
        sub=args.work/name
        logs=[(sub/(stage+'.log')).read_text(encoding='utf8',errors='replace')
              for stage in report['stages'] if stage.startswith('native-')]
        if len(logs)!=2 or not all('!Initial solution not found!' in log for log in logs):
            continue
        then=perf_counter()
        rec=geometric[name]
        _,p,_=problem_at(sub)
        with (sub/'shared-30.log').open('w',encoding='utf8') as log:
            proc=subprocess.run([str(args.atpython.resolve()),str(Path(__file__).with_name('atplace_shared_fv.py')),
                                 str(args.upstream.resolve()),str(sub.resolve()),'shared',sys.executable,
                                 '--projected-labels','--native-limit-s','30'],stdout=log,stderr=subprocess.STDOUT)
        result=dict(exit=proc.returncode,new_board_checks=0,**log_outcome(sub/'shared-30.log'))
        if proc.returncode==0:
            pose=from_atplace(p,json.loads((sub/'shared.json').read_bytes()))
            row=inspect(p,pose,np.asarray(rec['reach_mm']),rec['cap_m'])
            if row['legal']:
                row['peak_c']=solve(thermal_case_data(p,pose,100,64))[0]['peak_power_layer_c']
                result['new_board_checks']=1
            row['bin_escape_utilization']=escape_util(p,pose)
            result['endpoint']=dict(row,centre_um=pose.centre_um.tolist(),rotation_deg=pose.rotation_deg.tolist())
        else:
            result['failure']=(sub/'shared-30.log').read_text(encoding='utf8',errors='replace').splitlines()[-1]
        result['incremental_s']=perf_counter()-then
        records[name]=result
        print(name,proc.returncode,result['incremental_s'],flush=True)
    write_json(args.output,records)


def repair(args):
    """Give the native target one geometry-only projection and one new thermal check."""
    geometric=json.loads(args.geometry.read_bytes())['cases']
    original=json.loads(args.external.read_bytes())
    warmed=json.loads(args.warm.read_bytes()) if args.warm else {}
    records={}
    for name,report in original.items():
        if 'start_peak_c' not in report:
            records[name]=dict(status=report['status'],new_board_checks=0)
            continue
        then=perf_counter()
        sub=args.work/name
        _,p,start=problem_at(sub)
        rec=geometric[name]
        reach=np.asarray(rec['reach_mm'])
        fallback=warmed.get(name,{})
        endpoint=report.get('endpoint') or fallback.get('endpoint')
        cells=[]
        data=dict(verified=None,cell_attempts=[],extra_checks=0)
        if endpoint:
            target=np.array(endpoint['centre_um'])
            data['target_source']='common-start ATPlace export' if fallback else 'native export'
            if endpoint['legal']:
                cells.append(('native',Layout(target,np.array(endpoint['rotation_deg']))))
        else:
            model_id=sha256((sub/'shared-fv.pt').read_bytes()).hexdigest() if (sub/'shared-fv.pt').exists() else ''
            prefix='shared' if fallback else 'native'
            checkpoint=sub/(prefix+'-before-legalization-'+model_id+'.npz')
            target=None
            if checkpoint.exists():
                terminal=np.load(checkpoint)
                names=np.load(sub/'sampled.npz')['names'].tolist()
                order=[names.index(n) for n in p.names]
                target=np.c_[terminal['x'],terminal['y']][order]
                data['terminal_target_um']=target.tolist()
                data['target_source']=prefix+' pre-legalization coordinates'
        accepted=[report['best']]
        if fallback and endpoint and endpoint['feasible'] and endpoint['bin_escape_utilization']<=1.:
            accepted.append(dict(peak_c=endpoint['peak_c'],wire_m=endpoint['wire_m'],origin='common-start ATPlace export'))
        if target is not None:
            cells.append(('shared start',start))
            for cell_name,anchor in cells:
                candidate=PinReachCell(p,anchor,100,reach,rec['cap_m']).toward(target)
                data['cell_attempts'].append(cell_name)
                if candidate is None:
                    continue
                row=inspect(p,candidate,reach,rec['cap_m'])
                row['bin_escape_utilization']=escape_util(p,candidate)
                if not row['feasible'] or row['bin_escape_utilization']>1.:
                    continue
                def matches(centres, turns):
                    return (np.array_equal(candidate.rotation_deg,turns) and
                            np.allclose(candidate.centre_um,centres,rtol=0.,atol=1e-7))
                if matches(start.centre_um,start.rotation_deg):
                    temp=report['start_peak_c']
                elif endpoint and 'peak_c' in endpoint and matches(endpoint['centre_um'],endpoint['rotation_deg']):
                    temp=endpoint['peak_c']
                else:
                    temp=solve(thermal_case_data(p,candidate,100,64))[0]['peak_power_layer_c']
                    data['extra_checks']=1
                data['verified']=dict(row,cell=cell_name,peak_c=temp,centre_um=candidate.centre_um.tolist(),
                                      rotation_deg=candidate.rotation_deg.tolist())
                accepted.append(dict(peak_c=temp,wire_m=row['wire_m'],origin='projected native target'))
                break
        data['best']=min(accepted,key=lambda r:(r['peak_c'],r['wire_m']))
        data['reverse_m']=min([report['reverse_m']]+[r['wire_m'] for r in accepted
                               if r['peak_c']<=report['start_peak_c']+1e-7])
        data['new_board_checks']=report['new_board_checks']+fallback.get('new_board_checks',0)+data['extra_checks']
        data['responses']=report['reduced_responses']
        data['repair_s']=perf_counter()-then
        data['cold_with_geometry_s']=report['cold_with_geometry_s']+fallback.get('incremental_s',0)+data['repair_s']
        records[name]=data
    write_json(args.output,records)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    command=ap.add_subparsers(dest='cmd',required=True)
    for name in ('sample','labels'):
        command.add_parser(name).add_argument('out',type=Path)
    parser=command.add_parser('run')
    for name in ('geometry','source','upstream','atpython','work','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser=command.add_parser('audit')
    for name in ('geometry','work','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser=command.add_parser('repair')
    parser.add_argument('--warm',type=Path)
    for name in ('geometry','work','external','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser=command.add_parser('warm')
    for name in ('geometry','work','external','upstream','atpython','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=ap.parse_args()
    if args.cmd=='run':
        run(args)
    elif args.cmd=='repair':
        repair(args)
    elif args.cmd=='warm':
        warm(args)
    elif args.cmd=='audit':
        reports=json.loads(args.output.read_bytes())
        protocol=json.loads(args.geometry.read_bytes())
        for name,report in reports.items():
            if 'start_peak_c' in report:
                _,problem,_=problem_at(args.work/name)
                audit_result(report,protocol['cases'][name],problem,args.work/name)
        write_json(args.output,reports)
    else:
        {'sample':sample,'labels':labels}[args.cmd](args.out)
