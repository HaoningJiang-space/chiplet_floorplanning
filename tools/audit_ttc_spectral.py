"""Post-numerical-failure continuum diagnostic; no measured data fit or tuning."""

import argparse
from pathlib import Path
import json
import shutil

import numpy as np

from validation.ttc_geometry import extract
from validation.measured_thermal import patterns
from validation.measured_sources import digest
from validation.ttc_spectral import transfer
from validation.sources import write_json,git_revision


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('results/physical-calibration'))
    ap.add_argument('--spatial',type=Path,default=Path('results/physical-calibration/ttc-spatial-v1'))
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    geometry=extract(args.root/'ttc-origin')
    previous=json.loads((args.root/'ttc-observation-v2/report.json').read_text())
    code=[Path(__file__),Path('tools/validation/ttc_spectral.py'),Path('tools/validation/ttc_geometry.py'),Path('tools/validation/measured_thermal.py')]
    for p in code:shutil.copyfile(p,args.output/p.name)
    report=dict(physical_model_qualified=False,scope='independent steady continuum for same declared hybrid boundary',
                provenance='Added after primary FV refinement failed; changes no primary model or measured predictions',
                mode_counts=[16,32,64,128,256,512,1024],git=git_revision(Path('.')),
                code_sha256={str(p):digest(p) for p in code},groups={})
    write_json(args.output/'frozen-inputs.json',report)
    power=np.array(list(patterns().values()))
    for group,g in previous['groups'].items():
        ga=g['end_refit']['fit']['parameters']['g_a_w_per_k']
        resolutions={}
        for mode in report['mode_counts']:
            r=transfer(geometry,group,ga,mode)
            resolutions[str(mode)]=r @ power.T
        finest=resolutions['1024']
        fv=np.load(args.spatial/(group+'-numerics.npz'))
        entry=dict(series_max_change_k={str(mode):float(np.max(abs(resolutions[str(mode)]-resolutions[str(mode//2)]))) for mode in report['mode_counts'][1:]},
                   fv_error_to_continuum_k={key:float(np.max(abs(fv[key]-finest))) for key in ('coarse','primary','xy_refined','z_refined')},
                   minimum_sensor_rise_k=float(finest.min()),
                   series_numerical_screen=bool(np.max(abs(resolutions['1024']-resolutions['512']))<.01))
        report['groups'][group]=entry
        np.savez_compressed(args.output/(group+'.npz'),**resolutions)
        print(group,entry,flush=True)
    write_json(args.output/'report.json',report)


if __name__=='__main__':main()
