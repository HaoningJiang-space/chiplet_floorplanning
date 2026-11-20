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
from compare_large_pool import write_json
from continuous_baseline_audit import escape_util
from continuous_reach_geometry import NAMES, PIN, inspect
from chiplet_floorplanning.placement.evaluate import sample_legal
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
    args=ap.parse_args()
    if args.cmd=='run':
        run(args)
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
