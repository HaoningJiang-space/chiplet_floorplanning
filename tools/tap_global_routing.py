"""Finite aggregate routing resources; success is not detailed-routing signoff."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow
from freeze_tap_geometry import box,verify


def key(u,v):
    return (min(u,v),max(u,v))


def bump_bins(domain,p,bin_um=1000):
    c=domain['chiplets'][p['id']];w,h,r=c['core_width_um'],c['core_height_um'],c['bump_ring_um']
    if r%45:raise ValueError('Expected integer 45 um bump rows')
    # Disjoint bottom, left, right, top strips; exact twice-um centres.
    strips=[(0,0,w+r,r),(0,r,r,h+r),(w+r,0,r,h+r),(r,h+r,w+r,r)]
    bins=Counter();x0,y0,_,_=box(domain,p);rotation=p['rotation_deg']
    for x,y,width,height in strips:
        for i in range(width//45):
            for j in range(height//45):
                a,b=2*x+45+90*i,2*y+45+90*j
                if rotation==90:a,b=2*(h+2*r)-b,a
                elif rotation==180:a,b=2*(w+2*r)-a,2*(h+2*r)-b
                elif rotation==270:a,b=b,2*(w+2*r)-a
                bins[((x0+a)//(2*bin_um),(y0+b)//(2*bin_um))]+=1
    return bins


def build_graph(domain,placements,bin_um=1000,pitch_um=2):
    verify(domain,placements)
    side=domain['interposer_side_um']
    if any(type(v) is not int or v<=0 for v in (bin_um,pitch_um)) or side%bin_um or bin_um%pitch_um:
        raise ValueError('Positive grid-aligned dimensions required')
    n=side//bin_um;plane=n*n;core={};access={};capacities={};chips={}
    def node(x,y,z):return z*plane+y*n+x
    def add(u,v,cap):capacities[key(u,v)]=cap
    for y in range(n):
        for x in range(n):
            h,v=node(x,y,0),node(x,y,1)
            for a,b,cap in [(h,v,(bin_um//pitch_um)**2)]+([(h,node(x+1,y,0),bin_um//pitch_um)] if x+1<n else [])+([(v,node(x,y+1,1),bin_um//pitch_um)] if y+1<n else []):
                add(a,b,cap);core[key(a,b)]=cap
    next_id=2*plane
    for p in sorted(placements,key=lambda p:p['id']):
        chip=next_id;next_id+=1;chips[p['id']]=chip;edges=[]
        for (x,y),count in sorted(bump_bins(domain,p,bin_um).items()):
            if not 0<=x<n or not 0<=y<n:raise ValueError('Bump outside graph')
            gate=next_id;next_id+=1
            for a,b in ((chip,gate),(gate,node(x,y,0)),(gate,node(x,y,1))):
                add(a,b,count);edges.append((a,b))
        access[p['id']]=edges
    return dict(core=core,access=access,capacities=capacities,chips=chips,node_count=next_id,
        bin_um=bin_um,track_pitch_um=pitch_um,grid_bins_per_side=n)


def allowed_arcs(graph,source,sink):
    arcs={}
    for u,v in graph['core']:
        arcs[u,v]=key(u,v);arcs[v,u]=key(u,v)
    for u,v in graph['access'][source]:arcs[u,v]=key(u,v)
    for u,v in graph['access'][sink]:arcs[v,u]=key(u,v)
    return arcs


def validate_demands(graph,demands):
    n=len(graph['chips'])
    if len(demands)!=n or any(len(row)!=n for row in demands):
        raise ValueError('Demand matrix shape mismatch')
    if any(type(v) is not int or v<0 for row in demands for v in row) or any(demands[i][i] for i in range(n)):
        raise ValueError('Nonnegative integer cross-chip demands required')


def verify_witness(graph,demands,flows):
    validate_demands(graph,demands)
    delivered={};usage=Counter()
    expected={(i,j):int(v) for i,row in enumerate(demands) for j,v in enumerate(row) if v}
    for f in flows:
        source,sink,amount=f['source'],f['sink'],f['amount']
        pair=(source,sink)
        if pair not in expected or pair in delivered or type(amount) is not int or amount!=expected[pair]:
            raise ValueError('Unexpected, duplicate or wrong demand')
        arcs=allowed_arcs(graph,source,sink);balance=Counter()
        for u,v,value in f['edges']:
            if any(type(x) is not int for x in (u,v,value)) or value<=0 or (u,v) not in arcs:
                raise ValueError('Invalid directed resource use')
            balance[u]+=value;balance[v]-=value;usage[arcs[u,v]]+=value
        required={graph['chips'][source]:amount,graph['chips'][sink]:-amount}
        if {u:v for u,v in balance.items() if v}!=required:
            raise ValueError('Flow conservation or delivery failure')
        delivered[pair]=amount
    if delivered!=expected:raise ValueError('Missing demand')
    if any(v>graph['capacities'][e] for e,v in usage.items()):raise ValueError('Shared resource capacity exceeded')
    return dict(status='verified_integer_flow_in_aggregate_resource_graph',routed_wire_units=sum(delivered.values()),
        used_resources=len(usage),max_core_utilization=max((usage[e]/c for e,c in graph['core'].items()),default=0),
        physical_qualified=False)


def route(graph,demands):
    validate_demands(graph,demands)
    remaining=graph['capacities'].copy();flows=[];total=graph['node_count'];super_source,super_sink=total,total+1
    order=sorted(((-v,i,j) for i,row in enumerate(demands) for j,v in enumerate(row) if v))
    for neg,source,sink in order:
        amount=-neg;arcs=allowed_arcs(graph,source,sink)
        records=[(u,v,remaining[e]) for (u,v),e in arcs.items() if remaining[e]>0]
        records += [(super_source,graph['chips'][source],amount),(graph['chips'][sink],super_sink,amount)]
        rows,cols,values=zip(*records)
        capacity=coo_matrix((np.array(values,dtype=np.int64),(rows,cols)),shape=(total+2,total+2)).tocsr()
        solution=maximum_flow(capacity,super_source,super_sink)
        if solution.flow_value!=amount:
            return dict(status='sequential_search_failed_unknown',failed_pair=[source,sink],required=amount,
                residual_maxflow=int(solution.flow_value),partial_flows=flows,physical_qualified=False)
        positive=solution.flow.tocoo();edges=[]
        for u,v,value in zip(positive.row,positive.col,positive.data):
            if value>0 and u<total and v<total:
                u,v,value=int(u),int(v),int(value)
                remaining[arcs[u,v]]-=value;edges.append([u,v,value])
        flows.append(dict(source=source,sink=sink,amount=amount,edges=edges))
    return dict(**verify_witness(graph,demands,flows),flows=flows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domains',type=Path,default=Path('docs/evidence/tap-geometry-domains.json'))
    p.add_argument('--case',choices=['ascend910','micro150','multigpu'],default='ascend910')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();source=args.domains.read_bytes()
    e=next(c for c in json.loads(source)['cases'] if c['domain']['name']==args.case)
    graph=build_graph(e['domain'],e['witness']['placement'])
    demands=[[int(v) for v in row] for row in e['domain']['connection_wire_demands']]
    result=route(graph,demands)
    result.update(case=args.case,placement=e['witness']['placement'],source_sha256=hashlib.sha256(source).hexdigest(),
        contract_sha256=hashlib.sha256(Path('docs/tap-global-routing-contract.md').read_bytes()).hexdigest(),
        graph_nodes=graph['node_count'],shared_resources=len(graph['capacities']))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('flows','partial_flows','placement')},indent=2))


if __name__=='__main__':main()
