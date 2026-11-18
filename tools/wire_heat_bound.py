"""Relax pin lengths, placement distances and multilayer mutual heating in one LP."""
from itertools import combinations, product

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.special import k0, k1

from chiplet_floorplanning.placement.geometry import rotate


def thermal_modes(cert):
    """Longest two decay lengths of the homogeneous multilayer extension, in mm."""
    layers = cert['stack']
    sheets = np.array([s['k']*s['t_m'] for s in layers])
    resistances = [a['t_m']/(2*a['k']) + a['contact_above_m2k_w'] + b['t_m']/(2*b['k'])
                   for a,b in zip(layers,layers[1:])]
    resistances.append(1/cert['h_w_m2k']+layers[-1]['t_m']/(2*layers[-1]['k']))
    to_sink = np.cumsum(resistances[::-1])[::-1]
    # The vertical chain has one grounded end. Its exact inverse is the common path resistance.
    vertical_inverse = to_sink[np.maximum.outer(np.arange(len(layers)),np.arange(len(layers)))]
    radii2, vectors = np.linalg.eigh(vertical_inverse*np.sqrt(np.outer(sheets,sheets)))
    z = next(i for i,s in enumerate(layers) if s['id']=='dies')
    weights = vectors[z]**2/(2*np.pi*sheets[z])
    assert radii2.min()>0 and np.isclose(2*np.pi*(weights@radii2),vertical_inverse[z,z],rtol=1e-10)
    return 1000*np.sqrt(radii2[-2:])/(1+1e-7), weights[-2:]*(1-1e-7)


def bundle_data(p, gap_mm):
    """Mean minimum wire and an orientation-independent centre-to-mean-pin allowance."""
    groups = {}
    internal_mm = 0.
    for (a,b),(oa,ob) in zip(p.pin_chip,p.pin_offset_um/1000):
        if a==b:
            internal_mm += abs(oa-ob).sum()
            continue
        if a>b:
            a,b,oa,ob=b,a,ob,oa
        groups.setdefault((int(a),int(b)),[]).append((oa,ob))
    edges = []
    for (a,b),pins in sorted(groups.items()):
        offsets = np.array(pins)
        best,allowance = np.inf,0.
        for ra,rb in product(range(0,360,90),repeat=2):
            diff = rotate(offsets[:,1],rb)-rotate(offsets[:,0],ra)
            allowance = max(allowance,np.linalg.norm(diff.mean(axis=0)))
            sa = p.size_um[a,::(-1 if ra%180 else 1)]/1000
            sb = p.size_um[b,::(-1 if rb%180 else 1)]/1000
            sep = (sa+sb)/2+gap_mm
            centre = -np.median(diff,axis=0)
            for axis,sign in product((0,1),(1,-1)):
                v = centre.copy()
                v[axis] = sign*max(sign*v[axis],sep[axis])
                best = min(best,np.abs(diff+v).sum(axis=1).mean())
        edges.append(dict(a=a,b=b,n=len(pins),min_mm=max(0.,best-1e-8),offset_mm=allowance+1e-8))
    return edges,internal_mm


class DistanceRelaxation:
    def __init__(self,p,cert,gap_mm):
        self.p = p
        self.self_k = np.array([d['self_floor_k'] for d in cert['dies']])
        assert [d['name'] for d in cert['dies']]==list(p.names)
        sizes = p.size_um/1000
        self.pairs = list(combinations(range(p.count),2))
        self.a,self.b = np.array(self.pairs).T
        self.pid = dict(zip(self.pairs,range(len(self.pairs))))
        self.edges,self.internal_mm = bundle_data(p,gap_mm)
        self.m = len(self.pairs)
        nvar = 2*self.m+len(self.edges)
        radii,weights = thermal_modes(cert)
        self.modes = dict(radii_mm=radii.tolist(),coeff_k_w=weights.tolist())
        smallest = sizes.min(axis=1)
        minspan = (smallest[self.a]+smallest[self.b])/2
        self.dmin = minspan+gap_mm-1e-8
        carrier = np.array(p.carrier_um)/1000
        self.dmax = np.linalg.norm(carrier[None,:]-minspan[:,None],axis=1)+1e-8
        assert np.all(self.dmax>self.dmin) and np.all(self.dmin>0)
        sigma2 = (sizes**2).sum(axis=1)/12
        variance = sigma2[self.a]+sigma2[self.b]
        low = np.sqrt(self.dmin**2+variance)
        high = np.sqrt(self.dmax**2+variance)
        slope = (high-low)/(self.dmax-self.dmin)
        rows,cols,vals,rhs = [],[],[],[]
        def add(indices,values,limit):
            rows.extend([len(rhs)]*len(indices))
            cols.extend(indices)
            vals.extend(values)
            rhs.append(limit)
        # The chord upper-bounds the RMS point distance. Each tangent lower-bounds the thermal kernel.
        for fraction in np.linspace(0,1,13):
            d = self.dmin+fraction*(self.dmax-self.dmin)
            ratio = (low+slope*(d-self.dmin))[:,None]/radii
            kernel = k0(ratio)@weights
            derivative = -slope*(k1(ratio)@(weights/radii))
            for j in range(self.m):
                add([j,self.m+j],[derivative[j],-1.],derivative[j]*d[j]-kernel[j]+1e-10)
        self.budget_row = np.zeros(nvar)
        triangles = set()
        for e,edge in enumerate(self.edges):
            i,j = edge['a'],edge['b']
            ij = self.pid[i,j]
            col = 2*self.m+e
            add([ij,col],[1.,-1.],edge['offset_mm'])
            self.budget_row[col] = edge['n']
            for k in range(p.count):
                if k in (i,j):
                    continue
                ik = self.pid[tuple(sorted((i,k)))]
                jk = self.pid[tuple(sorted((j,k)))]
                for target,x,y in [(ik,ij,jk),(jk,ij,ik)]:
                    triangles.add((target,min(x,y),max(x,y)))
        for target,x,y in sorted(triangles):
            add([target,x,y],[1.,-1.,-1.],1e-9)
        self.cohorts = []
        for cut in sorted(set(np.round(self.self_k,8)),reverse=True):
            group = np.flatnonzero(np.round(self.self_k,8)>=cut)
            if group.size<2:
                continue
            self.cohorts.append(group)
            members = np.flatnonzero(np.isin(self.a,group) & np.isin(self.b,group))
            mass = p.power_w[self.a[members]]*p.power_w[self.b[members]]
            span = np.linalg.norm(carrier-smallest[group].min())
            # Sum of weighted squared pair distances = total mass squared times spatial variance.
            if mass.sum()>0:
                max_mean = span*p.power_w[group].sum()/(2*np.sqrt(mass.sum()))
                add(members,mass/mass.sum(),max_mean+1e-8)
        self.base_matrix = coo_matrix((vals,(rows,cols)),shape=(len(rhs),nvar)).tocsr()
        self.base_rhs = np.array(rhs)
        self.lo = np.r_[self.dmin,np.zeros(self.m),[e['min_mm'] for e in self.edges]]
        max_kernel = k0(low[:,None]/radii)@weights
        # The auxiliary kernel variable can equal the chord kernel at the actual centre distance.
        self.hi = np.r_[self.dmax,max_kernel+1e-8,
                        np.full(len(self.edges),carrier.sum()+2*np.abs(p.pin_offset_um/1000).max(axis=(0,1)).sum()+1)]
        self.box = np.column_stack([self.lo,self.hi])
        self.prior_floor_c = cert['floor_c']
        self.ambient_c = cert['ambient_c']

    def lower(self,cap_m):
        from scipy.sparse import vstack
        A,b = self.base_matrix,self.base_rhs
        if cap_m is not None:
            A = vstack([A,self.budget_row[None,:]],format='csr')
            b = np.r_[b,cap_m*1000-self.internal_mm+1e-7]
        results=[]
        for group in self.cohorts:
            power=self.p.power_w
            total=power[group].sum()
            members=np.isin(self.a,group)&np.isin(self.b,group)
            cost=np.zeros(len(self.lo))
            cost[self.m:2*self.m] = np.where(members,2*power[self.a]*power[self.b]/total,0)
            res=linprog(cost,A_ub=A,b_ub=b,bounds=self.box,method='highs')
            if not res.success:
                raise ValueError(res.message)
            # Any nonnegative multipliers certify a lower bound after minimizing over the finite box.
            multiplier = np.maximum(0.,-res.ineqlin.marginals)
            residual = cost+A.T@multiplier
            dual = float(np.where(residual>=0,self.lo,self.hi)@residual-b@multiplier)
            assert dual<=res.fun+1e-6
            mutual = max(0.,dual-1e-6)
            self_mean = float(power[group]@self.self_k[group]/total)
            results.append(dict(dies=group.tolist(),self_mean_k=self_mean,mutual_floor_k=mutual,
                                duality_gap_k=float(res.fun-dual),total_floor_c=self.ambient_c+self_mean+mutual,
                                wire_dual_k_per_m=(float(multiplier[-1])*1000 if cap_m is not None else 0.)))
        lower = max([self.prior_floor_c,*[r['total_floor_c'] for r in results]])
        return dict(cap_m=cap_m,floor_c=max(self.prior_floor_c,np.floor(100*lower)/100),groups=results)
