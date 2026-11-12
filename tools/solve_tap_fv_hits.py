"""Solve the frozen cell-centred TAP research model using local HiTS."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.power import rasterize


def run(case,hits_path):
    sys.path.insert(0,str(hits_path.resolve()))
    from hits import HiTS,ThermalOperator,EquationConvention,NodeRegion
    power,mapping=rasterize(case)
    started=time.perf_counter()
    a,b,g,nodes,ids,power_z=assemble_package(case,power)
    assembly_seconds=time.perf_counter()-started
    # Row equilibration preserves the temperature-rise unknown exactly.
    scale=1/a.diagonal()
    scaled=(sparse.diags(scale)@a).tocsr();scaled.sort_indices()
    regions=[]
    for z,layer in enumerate(case.thermal['layers']):
        active=ids[z][ids[z]>=0]
        if active.size:
            regions.append(NodeRegion(int(active.min()),int(active.max())+1,'SOLID',layer['id'],z,z==power_z))
    convention=EquationConvention('K rise','s','dimensionless','K','not used','left row scaling by reciprocal conductance diagonal','A theta = power','top and bottom Robin boundaries; zero ambient rise')
    q=ThermalOperator(scaled,scale*b,None,convention,'active layer-row-column',tuple(regions),
        'chiplet_floorplanning.package','fv-research-v1',case.name,('geometry-material-boundary','none','power'))
    theta,receipt=HiTS().solve_steady(q)
    ref=spsolve(a,b)
    residual=a@theta-b
    doubled=copy.deepcopy(case.input_data);doubled['thermal']['top_h_w_m2k']*=2
    other,_,_,_,_,_=assemble_package(parse_case(doubled),power)
    internal=a.copy();internal.setdiag(0);internal.eliminate_zeros()
    delta=other-a;delta.setdiag(0);delta.eliminate_zeros()
    symmetry=a-a.T
    rr=float(np.linalg.norm(residual)/max(np.linalg.norm(b),np.finfo(float).tiny))
    summary=dict(case=case.name,nodes=len(b),mesh=[case.nx,case.ny],assembly_seconds=assembly_seconds,
        source_power_w=float(b.sum()),mapped_power_w=float(power.sum()),heat_removed_w=float(g@theta),
        energy_balance_error_w=float(g@theta-b.sum()),original_relative_residual=rr,
        max_reference_difference_k=float(abs(theta-ref).max()),min_rise_k=float(theta.min()),
        peak_power_layer_c=float(theta[ids[power_z][ids[power_z]>=0]].max()+case.thermal['ambient_c']),
        max_internal_coefficient_change_w_k=float(abs(delta.data).max()) if delta.nnz else 0,
        max_asymmetry_w_k=float(abs(symmetry.data).max()) if symmetry.nnz else 0,
        max_offdiagonal_w_k=float(internal.data.max()),hits_receipt=receipt,power_mapping=mapping,
        physical_calibrated=False,scope='frozen FV research model; not HotSpot reproduction or routing benchmark')
    summary['numerical_admission_passed']=bool(receipt['accepted'] and rr<=1e-8 and abs(summary['energy_balance_error_w'])<=1e-4
        and summary['max_reference_difference_k']<=1e-3 and summary['min_rise_k']>=-1e-8
        and summary['max_internal_coefficient_change_w_k']==0 and summary['max_asymmetry_w_k']==0 and summary['max_offdiagonal_w_k']<=0)
    return summary,theta,a,b


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',type=Path,required=True)
    p.add_argument('--hits',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    summary,theta,a,b=run(load_case(args.case),args.hits)
    summary['input_sha256']=hashlib.sha256(args.case.read_bytes()).hexdigest()
    np.save(args.output/'temperature-rise.npy',theta);sparse.save_npz(args.output/'A.npz',a);np.save(args.output/'power.npy',b)
    (args.output/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='power_mapping'},indent=2),flush=True)
    if not summary['numerical_admission_passed']:raise SystemExit('Numerical admission failed; no physical infeasibility claim')


if __name__=='__main__':main()
