"""Diagnose rigidity with geometry alone after the bounded thermal comparison."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.optimize import linprog

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from continuous_metrics import inspect
from evidence_io import write_json


def audit(source,protocol):
    report={}
    for name,row in protocol['cases'].items():
        if not row['start']:
            continue
        clock=perf_counter()
        p=Problem.from_imported(json.loads((source/(name+'.json')).read_bytes()))
        s=row['start']
        start=Layout(np.array(s['centre_um']),np.array(s['rotation_deg']))
        limits=np.array(row['reach_mm'])
        cell=PinReachCell(p,start,100,limits,row['cap_m'])
        xy=start.centre_um.T.ravel()/1000
        directions=[]
        for i in np.argsort(-(p.power_w/p.size_um.prod(axis=1)),kind='stable')[:2]:
            solo=list(cell.bounds)
            for j,t in enumerate(xy):
                if j%p.count!=i:
                    solo[j]=(t,t)
            for axis,sign in ((0,-1),(0,1),(1,-1),(1,1)):
                target=axis*p.count+i
                objective=np.zeros(cell.nvar)
                objective[target]=-sign
                record=dict(die=p.names[i],axis=axis,sign=sign)
                for label,bounds in [('solo',solo),('joint',cell.bounds)]:
                    result=linprog(objective,A_ub=cell.A,b_ub=cell.b,bounds=bounds,method='highs')
                    if not result.success:
                        raise ValueError(result.message)
                    record[label+'_max_mm']=max(0.,float(sign*(result.x[target]-xy[target])))
                    if label=='joint':
                        pose=cell.toward(result.x[:2*p.count].reshape(2,p.count).T*1000)
                        if pose is not None and inspect(p,pose,limits,row['cap_m'])['feasible']:
                            delta=(pose.centre_um-start.centre_um)/1000
                            record.update(witness_mm=float(sign*delta[i,axis]),
                                          relative_span_change_mm=float(np.ptp(delta[:,axis])),
                                          moved_dies=int((np.max(abs(delta),axis=1)>1e-5).sum()))
                directions.append(record)
        report[name]=dict(directions=directions,elapsed_s=perf_counter()-clock)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','geometry','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    write_json(args.output,audit(args.source,json.loads(args.geometry.read_bytes())))
