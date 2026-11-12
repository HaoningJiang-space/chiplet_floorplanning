"""Secondary spatial-difference continuum diagnostic, no new fit."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from validation.ttc_spectral import transfer
from validation.ttc_geometry import extract
from validation.measured_sources import verify,digest
from validation.measured_thermal import read_trace,predict
from validation.ttc_observation import raw_metrics
from validation.sources import write_json,git_revision


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('results/physical-calibration'))
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();verify(args.root)
    geo=extract(args.root/'ttc-origin')
    admission_path=args.root/'thermal-fit-v2/report.json'
    base_path=args.root/'ttc-observation-v2/report.json'
    admission=json.loads(admission_path.read_text());baseline=json.loads(base_path.read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    code=[Path(__file__),Path('tools/validation/ttc_spectral.py'),Path('docs/ttc-spatial-plan.md'),
          Path('tools/validation/measured_thermal.py'),Path('tools/validation/ttc_geometry.py')]
    for p in code:shutil.copyfile(p,args.output/p.name)
    report=dict(physical_model_qualified=False,no_new_fit=True,
                scope='post-FV secondary approximate-DC sensor differences, conditional on uniform bath',
                git=git_revision(Path('.')),code_sha256={str(p):digest(p) for p in code},
                admission_sha256=digest(admission_path),baseline_sha256=digest(base_path),groups={})
    write_json(args.output/'frozen-inputs.json',report)
    projection=np.eye(16)-np.ones((16,16))/16
    for group,records in admission['groups'].items():
        material=geo['materials']['natural' if group=='heatsink' else 'fan']
        tau=4*(sum(geo[k] for k in ('active_silicon_um','bulk_silicon_um','thermal_pad_um'))*1e-6)**2
        tau*=max(m['volumetric_capacity_j_per_m3_k'] for m in material.values())/(np.pi**2*min(m['conductivity_w_per_m_k'] for m in material.values()))
        resistance=transfer(geo,group,1.,1024)
        spatial=projection @ resistance
        # Changing only the common bath resistance must vanish under projection.
        independence=float(np.max(abs(projection @ (resistance+9.)-spatial)))
        parameters=baseline['groups'][group]['end_refit']['fit']['parameters']
        logg=np.log([parameters[k] for k in ('g_xy_w_per_k','g_z_w_per_k','g_a_w_per_k')])
        result=dict(internal_relaxation_upper_bound_s=float(tau),
                    uniform_bath_resistance_independence_error_k_per_w=independence,cases=[])
        for record in records['cases']:
            name=record['name']
            v,i,t=read_trace(args.root/'thermal-original/release'/group/(name+'.csv'))
            end=record['activation_end_exclusive']-10
            start=end-90
            if start<record['activation_start_index']:raise ValueError('window before main activation')
            p=(v*i)[start:end];temperature=t[start:end]
            delta=temperature @ projection
            meanp=p.mean(axis=0);measured=delta.mean(axis=0)
            proposed=spatial @ meanp
            old=projection @ predict(logg,meanp)
            pdrift=float(np.linalg.norm(p[45:].mean(axis=0)-p[:45].mean(axis=0))/np.linalg.norm(meanp))
            tdrift=float(np.max(abs(delta[45:].mean(axis=0)-delta[:45].mean(axis=0))))
            result['cases'].append(dict(name=name,role=record['role'],start_raw_row=start,end_raw_row_exclusive=end,
                elapsed_since_activation_s=(start-record['activation_start_index'])*.1,
                channel_power_relative_drift=pdrift,spatial_temperature_drift_k=tdrift,
                approximate_dc_screen=bool(pdrift<=.02 and tdrift<=.1),power_w=meanp.tolist(),
                measured_sensor_difference_k=measured.tolist(),baseline_sensor_difference_k=old.tolist(),
                continuum_sensor_difference_k=proposed.tolist(),
                baseline_error=raw_metrics((old-measured)[None,:]),continuum_error=raw_metrics((proposed-measured)[None,:])))
        result['summary']={}
        for role in ('calibration','held_out'):
            rows=[c for c in result['cases'] if c['role']==role]
            result['summary'][role]=dict(case_count=len(rows),passed_dc_screen=sum(c['approximate_dc_screen'] for c in rows),
                baseline_spatial_rmse_k=float(np.sqrt(np.mean([c['baseline_error']['rmse_k']**2 for c in rows]))),
                continuum_spatial_rmse_k=float(np.sqrt(np.mean([c['continuum_error']['rmse_k']**2 for c in rows]))),
                improved_patterns=sum(c['continuum_error']['rmse_k']<c['baseline_error']['rmse_k'] for c in rows))
        report['groups'][group]=result
        print(group,result['summary'],'tau_bound_s',tau,flush=True)
    write_json(args.output/'report.json',report)


if __name__=='__main__':main()
