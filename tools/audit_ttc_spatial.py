"""Frozen source-geometry falsification with an unchanged dynamic sink."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter

import numpy as np
from scipy.sparse import csr_matrix,diags
from scipy.sparse.linalg import splu

from calibrate_measured_transient import case_data
from validation.measured_sources import verify,digest
from validation.measured_thermal import patterns
from validation.measured_transient import matrices
from validation.sources import git_revision,write_json
from validation.ttc_geometry import extract
from validation.ttc_observation import PARAMETERS,raw_metrics
from validation.ttc_spatial import build,Network,Modal,initialize


def network_audit(n, powers):
    state=splu(n.g.tocsc()).solve(n.b @ powers.T)
    residual=n.g @ state-n.b @ powers.T
    sink=np.asarray(n.g.sum(axis=0)).ravel()
    off=n.g-diags(n.g.diagonal())
    gdiff=n.g-n.g.T
    group_flux=[]
    for layer in n.metadata['layer_indices']:
        ids=np.asarray(layer).ravel()
        group_flux.append(np.asarray(n.g[ids].sum(axis=0)).ravel() @ state)
    expected=np.zeros_like(group_flux);expected[0]=powers.sum(axis=1)
    return n.h @ state,dict(node_count=len(n.c),positive_capacity=bool(np.min(n.c)>0),
        reciprocal=bool(gdiff.nnz==0 or np.max(abs(gdiff.data))<1e-12),
        nonpositive_offdiagonal=bool(off.nnz==0 or np.max(off.data)<=1e-12),
        boundary_row_sum_error_w_per_k=float(np.max(abs(sink-np.r_[np.zeros(len(n.c)-1),n.metadata['ga_w_per_k']]))),
        capacity_j_per_k=float(n.c.sum()),steady_local_residual_w=float(np.max(abs(residual))),
        steady_power_balance_w=float(np.max(abs(sink @ state-powers.sum(axis=1)))),
        layer_net_flux_balance_w=float(np.max(abs(np.array(group_flux)-expected))),
        minimum_steady_rise_k=float(state.min()))


def short_steps(n,powers,dt):
    """Independent implicit solver, all spatial patterns at once; no fitting."""
    p0=np.full((16,len(powers)),.2)
    state=splu(n.g.tocsc()).solve(n.b @ p0)
    factor=splu((n.g+diags(n.c/dt)).tocsc())
    result=[]
    steps=round(1/dt); stride=round(.1/dt)
    for step in range(steps):
        source=powers.T if step < steps//2 else p0
        state=factor.solve(n.b @ source+n.c[:,None]/dt*state)
        if (step+1)%stride==0:
            result.append(n.h @ state)
    return np.array(result)


def numerical_controls(geometry,group,ga,cb,folder):
    nominal=np.array(list(patterns().values()))
    settings={'coarse':(1000.,2,2),'primary':(500.,2,2),'xy_refined':(250.,2,2),'z_refined':(500.,4,4)}
    states={}; diagnostics={}; transient={}; primary=None
    for key,(pitch,bulk,pad) in settings.items():
        n=build(geometry,group,ga,cb,pitch,bulk,pad)
        states[key],diagnostics[key]=network_audit(n,nominal)
        print(group,'numerical',key,diagnostics[key],flush=True)
        if key=='primary':
            primary=n
            for dt in (.01,.005,.0025):
                transient[str(dt)]=short_steps(n,nominal,dt)
        elif key in ('xy_refined','z_refined'):
            transient[key]=short_steps(n,nominal,.0025)
    errors={key:float(np.max(abs(value-states['primary']))) for key,value in states.items() if key!='primary'}
    time_error=float(np.max(abs(transient['0.0025']-transient['0.005'])))
    transient_errors={key:float(np.max(abs(transient[key]-transient['0.0025']))) for key in ('xy_refined','z_refined')}
    result=dict(grids=diagnostics,nominal_pattern_names=list(patterns()),
                steady_sensor_difference_k=errors,transient_sensor_difference_k=transient_errors,
                be_halving_difference_k=time_error,
                primary_numerical_screen=bool(max(errors['xy_refined'],errors['z_refined'],*transient_errors.values(),time_error)<=.1),
                threshold_k=.1)
    np.savez_compressed(folder/(group+'-numerics.npz'),**states,**{'step_'+k:v for k,v in transient.items()})
    return primary,result


def scores(prediction,case):
    error=prediction-case['temperature_rise_k']
    common=error.mean(axis=1,keepdims=True)
    spatial=error-common
    time=np.arange(len(error))*.1
    events=np.array([case['activation_offset'],case['end_power_offset']])*.1
    switch=np.min(abs(time[:,None]-events),axis=1)<=1.00000001
    output=dict(raw=raw_metrics(error),common_rmse_k=float(np.sqrt(np.mean(common**2))),
                spatial_rmse_k=float(np.sqrt(np.mean(spatial**2))),
                first_60s=raw_metrics(error[:600]),after_60s=raw_metrics(error[600:]),
                switch_events=raw_metrics(error[switch]),
                spatial_after_60s_rmse_k=float(np.sqrt(np.mean(spatial[600:]**2))),
                spatial_switch_rmse_k=float(np.sqrt(np.mean(spatial[switch]**2))),
                per_sensor_bias_k=error.mean(axis=0).tolist())
    ix=np.unravel_index(np.argmax(abs(error)),error.shape)
    output['worst']=dict(row=int(ix[0]),sensor=int(ix[1]),signed_error_k=float(error[ix]))
    return output


def summarize(entries,variant):
    result={}
    for role in ('calibration','held_out'):
        cases=[c[variant] for c in entries if c['role']==role]
        result[role]=dict(case_count=len(cases),
            rmse_k=float(np.sqrt(np.mean([c['raw']['rmse_k']**2 for c in cases]))),
            mae_k=float(np.mean([c['raw']['mae_k'] for c in cases])),
            max_error_k=max(c['raw']['max_abs_error_k'] for c in cases),
            common_rmse_k=float(np.sqrt(np.mean([c['common_rmse_k']**2 for c in cases]))),
            spatial_rmse_k=float(np.sqrt(np.mean([c['spatial_rmse_k']**2 for c in cases]))),
            spatial_after_60s_rmse_k=float(np.sqrt(np.mean([c['spatial_after_60s_rmse_k']**2 for c in cases]))),
            switch_max_error_k=max(c['switch_events']['max_abs_error_k'] for c in cases))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('results/physical-calibration'))
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    verify(args.root)
    geo=extract(args.root/'ttc-origin')
    order_lock=Path('tools/ttc-layer-order.lock.json')
    for record in json.loads(order_lock.read_text())['files']:
        if digest(args.root/'ttc-origin'/record['path'])!=record['sha256']:
            raise ValueError('layer order source mismatch')
    baseline_path=args.root/'ttc-observation-v2/report.json'
    admission_path=args.root/'thermal-fit-v2/report.json'
    previous=json.loads(baseline_path.read_text())
    admission=json.loads(admission_path.read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    code=[Path(__file__),Path('tools/validation/ttc_spatial.py'),Path('tools/validation/ttc_geometry.py'),
          Path('tools/calibrate_measured_transient.py'),Path('tools/validation/measured_thermal.py'),
          Path('tools/validation/measured_transient.py'),Path('tools/validation/ttc_observation.py'),
          Path('docs/ttc-spatial-plan.md'),order_lock,Path('tools/ttc-upstream.lock.json'),Path('tools/measured-sources.lock.json')]
    for p in code:shutil.copyfile(p,args.output/p.name)
    report=dict(physical_model_qualified=False,no_new_fit=True,
                scope='hybrid internal geometry falsification with previous fitted dynamic sink; not complete 3D-ICE',
                git=git_revision(Path('.')),baseline_sha256=digest(baseline_path),admission_sha256=digest(admission_path),
                code_sha256={str(p):digest(p) for p in code},geometry=geo,groups={})
    write_json(args.output/'frozen-inputs.json',report)
    for group,admitted in admission['groups'].items():
        pars=previous['groups'][group]['end_refit']['fit']['parameters']
        ga,cb=pars['g_a_w_per_k'],pars['c_bath_j_per_k']
        n,numerics=numerical_controls(geo,group,ga,cb,args.output)
        g,c,_=matrices(np.log([pars[key] for key in PARAMETERS]))
        old=Network(csr_matrix(g),c,np.r_[np.eye(16),np.zeros((1,16))],np.c_[np.eye(16),np.zeros(16)],{})
        ms,mb=Modal(n),Modal(old)
        result=dict(numerics=numerics,network=n.metadata,baseline_parameters=pars,cases=[],
                    spatial_modal_setup_seconds=ms.setup_seconds)
        report['groups'][group]=result
        write_json(args.output/'progress.json',report)
        folder=args.output/group;folder.mkdir()
        for record in admitted['cases']:
            case=case_data(args.root,group,record)
            entry=dict(name=case['name'],role=case['role'])
            waves={}
            for name,model in [('baseline',mb),('spatial',ms)]:
                for uniform in (False,True):
                    variant=name+('_uniform' if uniform else '')
                    initial=initialize(model.network,case['power_w'],case['initial_cells_k'],uniform)
                    prediction,ledger=model.run(case['power_w'],initial)
                    entry[variant]=dict(**scores(prediction,case),ledger=ledger,
                                       initial_mean_k=float((model.network.h @ initial).mean()),
                                       initial_bath_k=float(initial[-1]))
                    if not uniform:
                        waves[name]=prediction
            ix=np.unique(np.r_[np.arange(0,len(case['power_w']),10),
                    np.arange(max(0,case['activation_offset']-10),min(len(case['power_w']),case['activation_offset']+11)),
                    np.arange(max(0,case['end_power_offset']-10),min(len(case['power_w']),case['end_power_offset']+11))])
            path=folder/(case['name']+'.npz')
            np.savez_compressed(path,time_s=ix*.1,measured_c=case['temperature_rise_k'][ix]+case['ambient_c'],
                                baseline_c=waves['baseline'][ix]+case['ambient_c'],spatial_c=waves['spatial'][ix]+case['ambient_c'],
                                power_w=case['power_w'][ix],event_times_s=np.array([case['activation_offset'],case['end_power_offset']])*.1)
            entry['waveform_sha256']=digest(path)
            result['cases'].append(entry)
            print(group,case['name'],'spatial RMSE',entry['baseline']['spatial_rmse_k'],entry['spatial']['spatial_rmse_k'],flush=True)
            write_json(args.output/'progress.json',report)
        result['summary']={v:summarize(result['cases'],v) for v in ('baseline','spatial','baseline_uniform','spatial_uniform')}
        old_rmse=result['summary']['baseline']['held_out']['spatial_rmse_k']
        new_rmse=result['summary']['spatial']['held_out']['spatial_rmse_k']
        improvement=old_rmse-new_rmse
        count=sum(c['spatial']['spatial_rmse_k']<c['baseline']['spatial_rmse_k'] for c in result['cases'] if c['role']=='held_out')
        mesh_error=max(numerics['steady_sensor_difference_k']['xy_refined'],numerics['steady_sensor_difference_k']['z_refined'],*numerics['transient_sensor_difference_k'].values())
        result['falsification']=dict(relative_spatial_rmse_reduction=improvement/old_rmse,improved_held_out_patterns=count,
            raw_effect_screen=bool(new_rmse<=.8*old_rmse and count>=7),
            numerical_error_below_tenth_improvement=bool(improvement>0 and mesh_error<=.1*improvement),
            qualified_spatial_improvement=bool(new_rmse<=.8*old_rmse and count>=7 and numerics['primary_numerical_screen'] and mesh_error<=.1*improvement))
        print(group,result['summary'],result['falsification'],flush=True)
        write_json(args.output/'progress.json',report)
    write_json(args.output/'report.json',report)


if __name__=='__main__':main()
