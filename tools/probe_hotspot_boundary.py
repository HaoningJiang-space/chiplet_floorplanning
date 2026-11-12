"""Probe whether external convection contaminates an internal HotSpot edge."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hits',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.hits.resolve()))
    from tools.native_io import read_hotspot
    source=args.input.resolve();out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    config={}
    for line in (source/'new_hotspot.config').read_text().splitlines():
        fields=line.split()
        if fields and fields[0].startswith('-'):
            config[fields[0]]=fields[1]
    baseline=float(config['-r_convec'])
    resistances=[];hashes=[]
    for label,value in [('baseline',baseline),('double',2*baseline)]:
        env=os.environ.copy();env.pop('HITS_HOTSPOT_REFERENCE',None)
        artifact=out/(label+'.bin');env['HITS_HOTSPOT_EXPORT']=str(artifact)
        cmd=[str(args.binary.resolve()),'-c',str(source/'new_hotspot.config'),'-f',str(source/'caseL4_ChipLayer.flp'),'-p',str(source/'case.ptrace'),'-model_type','grid','-detailed_3D','on','-grid_layer_file',str(source/'caselayers.lcf'),'-r_convec',str(value)]
        with (out/(label+'.log')).open('w') as log:
            subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        a,b,regions,shape=read_hotspot(artifact)
        if shape!=(64,64,8):raise ValueError('Expected TAP native shape')
        # Interior cell, avoiding all peripheral package-edge connections.
        lo=6*64*64+32*64+32;hi=lo+64*64
        resistances.append(float(-1/a[lo,hi]))
        hashes.append(hashlib.sha256(artifact.read_bytes()).hexdigest())
    area=.05**2/(64*64)
    conduction=(float(config['-t_spreader'])/float(config['-k_spreader'])+float(config['-t_sink'])/float(config['-k_sink']))/(2*area)
    predicted=baseline*float(config['-s_sink'])**2/(2*area)
    result=dict(status='internal_edge_depends_on_external_convection',
        scope='diagnostic only; no coefficient patch or candidate layout experiment',
        convection_k_w=[baseline,2*baseline],internal_edge_resistance_k_w=resistances,
        material_half_cell_resistance_k_w=conduction,
        predicted_spurious_increment_k_w=predicted,
        observed_increment_k_w=resistances[1]-resistances[0],
        absolute_prediction_error_k_w=abs(resistances[1]-resistances[0]-predicted),
        physical_invariance_passed=abs(resistances[1]-resistances[0])<1e-10,
        artifact_sha256=hashes,
        source_input_manifest_sha256=hashlib.sha256((source/'inputs.json').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
