"""Freeze the interconnect contract and a geometric start without evaluating temperature."""
import argparse
from hashlib import sha256
import json
from itertools import product
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.sparse.csgraph import floyd_warshall
from scipy.sparse.csgraph import NegativeCycleError
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy import sparse

from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.geometry import pin_points_um, rotate
from chiplet_floorplanning.placement.pin_reach import PinReachCell, reach_rows
from chiplet_floorplanning.placement.lp import TopologyLP, legalize_relations
from chiplet_floorplanning.placement.evaluate import sample_legal
from common_relocation import ORIGINAL
from compare_large_pool import write_json
from import_atplace_cases import PIN


NAMES = ('Case1','Case7','Case8')


def limits(p):
    if p.name == 'Case1':
        return np.full(len(p.pin_chip), 2.)
    peripheral = np.array([s.startswith(('MEMS','Analog')) for s in p.names])
    return np.where(peripheral[p.pin_chip].all(axis=1), 10., 25.)


def inspect(p, layout, reach, cap):
    pins = pin_points_um(p,layout)/1000
    length = np.abs(pins[:,0]-pins[:,1]).sum(axis=1)
    excess = length-reach
    # Full-carrier cuts on 1 mm bin boundaries. The last partial bin contributes
    # exactly its available track width. Tracks under the dies are usable.
    side = np.array(p.carrier_um)/1000
    cut = 0.
    for axis in (0,1):
        ends = np.sort(pins[:,:,axis],axis=1)
        borders = np.arange(1.,side[axis])
        cross = (np.searchsorted(np.sort(ends[:,0]),borders,side='left')
                 - np.searchsorted(np.sort(ends[:,1]),borders,side='left'))
        cut = max(cut, float(cross.max(initial=0)/np.floor(side[1-axis]*500)))
    geom = is_legal(p,layout,100)
    wire = float(length.sum()/1000)
    return dict(legal=geom, wire_m=wire, max_net_mm=float(length.max()),
                reach_violations=int((excess>1e-9).sum()),worst_excess_mm=max(0.,float(excess.max())),
                full_cut_utilization=cut,
                feasible=bool(geom and wire<=cap+1e-9 and excess.max()<=1e-9 and cut<=1.))


def cycle_audit(p, reach):
    """Remove carrier and overlap; a negative directed cycle still rules out a pose."""
    a,b = p.pin_chip.T
    pairs = np.unique(np.sort(p.pin_chip,axis=1),axis=0)
    tables = {}
    for i,j in pairs:
        ix = ((a==i)&(b==j))|((a==j)&(b==i))
        first = np.where((a[ix]==i)[:,None],p.pin_offset_um[ix,0],p.pin_offset_um[ix,1])
        second = np.where((a[ix]==i)[:,None],p.pin_offset_um[ix,1],p.pin_offset_um[ix,0])
        for r,s in product(range(4),repeat=2):
            diff = (rotate(first,90*r)-rotate(second,90*s))/1000
            u,v = diff.sum(axis=1),diff[:,0]-diff[:,1]
            tables[i,j,r,s] = [float((reach[ix]-d).min()) for d in (u,-u,v,-v)]
    possible = []
    for tail in product(range(4),repeat=p.count-1):
        turns = (0, *tail)  # whole-board rotation symmetry in this carrier-free relaxation
        graph = np.full((2,p.count,p.count),np.inf)
        for i,j in pairs:
            up,um,vp,vm = tables[i,j,turns[i],turns[j]]
            graph[:,i,j] = um,vm
            graph[:,j,i] = up,vp
        try:
            for plane in graph:
                # Positive numerical slack makes a contradiction conservative.
                floyd_warshall(plane+1e-8,directed=True)
        except NegativeCycleError:
            continue
        possible.append(turns)
    return dict(orientations=4**(p.count-1), surviving=len(possible),surviving_turns=possible)


def rectangular_audit(p, reach, survivors):
    """Exhaust all four separating sides only for overlapping pairs in an LP witness."""
    from chiplet_floorplanning.placement.geometry import violations
    n = p.count
    nodes = 0
    for turns in survivors:
        rot = 90*np.asarray(turns)
        size = np.where((rot%180!=0)[:,None],p.size_um[:,::-1],p.size_um)/1000
        bounds = [(s/2,w/1000-s/2) for axis,w in enumerate(p.carrier_um) for s in size[:,axis]]
        mat,rhs = reach_rows(p,rot,reach+1e-8,2*n)
        stack = [(mat,rhs)]
        while stack:
            mat,rhs = stack.pop()
            nodes += 1
            lp = linprog(np.zeros(2*n),A_ub=mat,b_ub=rhs,bounds=bounds,method='highs')
            if lp.status==2:
                continue
            if not lp.success:
                raise RuntimeError(lp.message)
            lay = Layout(lp.x.reshape(2,n).T*1000,rot)
            conflict = violations(p,lay,100.-1e-4)['pairs']
            if not conflict:
                return nodes,lay
            i,j = map(p.names.index,conflict[0])
            for axis,sgn in product((0,1),(-1,1)):
                row = np.zeros(2*n)
                row[axis*n+i],row[axis*n+j] = sgn,-sgn
                stack.append((sparse.vstack((mat,row[None])),np.r_[rhs,-(size[i,axis]+size[j,axis])/2-.1+1e-8]))
    return nodes,None


def repair_orders(p, anchor, reach, cap):
    """Open side choices only for pairs that actually collide in a relaxed placement."""
    n = p.count
    base = TopologyLP(p,anchor,100,relations=[])
    rows,b = reach_rows(p,base.rotation,reach-.002001,base.nvar)
    fixed = sparse.vstack((base.A,rows,base.length[None]),format='csr')
    xy0 = anchor.centre_um.T.ravel()/1000
    ident = sparse.eye(2*n,base.nvar,format='csr')
    fixed = sparse.bmat([[fixed,None],[ident,-sparse.eye(2*n)],[-ident,-sparse.eye(2*n)]],format='csr')
    rhs = np.r_[base.b,b,cap*1000-base.internal_mm-.002001*len(reach),xy0,-xy0]
    size = np.where((base.rotation%180!=0)[:,None],p.size_um[:,::-1],p.size_um)/1000
    pairs = set()
    solves = []
    for _ in range(12):
        k = base.nvar+2*n
        nr = len(pairs)*4
        columns = k+nr
        mat = sparse.hstack((fixed,sparse.csr_matrix((len(rhs),nr))),format='csr')
        rows,ub = [],[]
        for t,(i,j) in enumerate(sorted(pairs)):
            group = k+4*t
            for h,(axis,sgn) in enumerate(product((0,1),(-1,1))):
                line = np.zeros(columns)
                maximum = p.carrier_um[axis]/1000+.101
                line[axis*n+i],line[axis*n+j],line[group+h]=sgn,-sgn,maximum
                rows.append(line)
                ub.append(maximum-(size[i,axis]+size[j,axis])/2-.10001)
            line = np.zeros(columns)
            line[group:group+4] = -1
            rows.append(line)
            ub.append(-1.)
        if rows:
            mat=sparse.vstack((mat,sparse.csr_matrix(rows)))
        low, high = zip(*base.bounds)
        bound=Bounds(np.r_[low,np.zeros(2*n+nr)],np.r_[[np.inf if x is None else x for x in high],np.full(2*n,np.inf),np.ones(nr)])
        ans=milp(np.r_[1e-8*base.length,np.ones(2*n),np.zeros(nr)],integrality=np.r_[np.zeros(k),np.ones(nr)],
                 bounds=bound,constraints=LinearConstraint(mat,-np.inf,np.r_[rhs,ub]),
                 options={'time_limit':10.,'mip_rel_gap':.25})
        solves.append(dict(pairs=len(pairs),status=int(ans.status),has_incumbent=ans.x is not None))
        if ans.x is None:
            return None,solves
        xy=ans.x[:2*n].reshape(2,n).T
        delta=abs(xy[:,None]-xy[None,:])-(size[:,None]+size[None,:])/2
        ii,jj=np.where(np.triu(delta.max(axis=2)<.1-1e-7,1))
        if len(ii)==0:
            lay=legalize_relations(p,Layout(xy*1000,base.rotation),100)
            if lay is not None:
                lay=PinReachCell(p,lay,100,reach,cap).toward(xy*1000)
            return lay,solves
        pairs.update(zip(ii,jj))
    return None,solves


def freeze(source, out):
    anchors = {x['name']:x for x in json.loads(ORIGINAL.read_bytes())['cases']}
    archive = {x['case']:x for x in json.loads((ORIGINAL.parents[1]/'layout-dominance-v1.json').read_bytes())['cases']}
    result = dict(seed=20261119,upstream=PIN,cases={})
    for name in NAMES:
        clock = perf_counter()
        raw = (source/(name+'.json')).read_bytes()
        data = json.loads(raw)
        assert data['source_commit'] == PIN and sha256(raw).hexdigest() == archive[name]['input_sha256']
        p = Problem.from_imported(data)
        a = anchors[name]
        anchor = Layout(np.array(a['anchor_xy_um']),np.array(a['rotation_deg']))
        cap = float(pin_manhattan_um(p,anchor).sum()/1e6)
        reach = limits(p)
        cycle = cycle_audit(p,reach) if name=='Case1' else None
        row = dict(source_sha256=sha256(raw).hexdigest(), reach_mm=reach.tolist(),
                   original_cap_m=cap,original=inspect(p,anchor,reach,cap),cycle=cycle,
                   die_names=p.names, fill=float(p.size_um.prod(axis=1).sum()/np.prod(p.carrier_um)),
                   n=p.count,nets=len(reach),start=None,attempted=0)
        geometries = [anchor] + [Layout(np.array(v['centre_um']),np.array(v['rotation_deg']))
                                 for v in sorted(archive[name]['layouts'],key=lambda v:v['layout'])]
        if cycle:
            nodes, witness = rectangular_audit(p,reach,cycle['surviving_turns'])
            cycle.update(separation_lp_nodes=nodes,rectangle_feasible=witness is not None)
            if witness is not None:
                geometries.insert(0,witness)
        if not cycle or cycle['rectangle_feasible']:
            rng = np.random.default_rng(20261119)
            def alternatives():
                yield from geometries
                for _ in range(20):
                    yield sample_legal(p,100,rng)
            for layout in alternatives():
                if not is_legal(p,layout,100):
                    layout = legalize_relations(p,layout,100)
                    if layout is None:
                        continue
                row['attempted'] += 1
                if not inspect(p,layout,reach,cap)['feasible']:
                    layout = PinReachCell(p,layout,100,reach,cap).toward(layout.centre_um)
                if layout is not None and inspect(p,layout,reach,cap)['feasible']:
                    metrics = inspect(p,layout,reach,cap)
                    row.update(start=dict(centre_um=layout.centre_um.tolist(),rotation_deg=layout.rotation_deg.tolist(),
                                          **metrics),cap_m=metrics['wire_m'])
                    break
            if row['start'] is None:
                layout,row['order_repair'] = repair_orders(p,anchor,reach,cap)
                if layout is not None:
                    metrics=inspect(p,layout,reach,cap)
                    if metrics['feasible']:
                        row.update(start=dict(centre_um=layout.centre_um.tolist(),
                                              rotation_deg=layout.rotation_deg.tolist(),**metrics),cap_m=metrics['wire_m'])
        row['geometry_s'] = perf_counter()-clock
        result['cases'][name] = row
        print(name,'geometry',row['attempted'],'cap',row.get('cap_m'),'surviving rotations',
              None if cycle is None else cycle['surviving'],flush=True)
    write_json(out,result)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    freeze(args.source,args.output)
