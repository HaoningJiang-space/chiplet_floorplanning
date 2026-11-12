"""Source-geometry TTC finite volumes and exact full-order transient response.

The lumped dynamic sink is deliberately retained from the previous fit. This
hybrid diagnostic is neither a full author-model reproduction nor calibration.
"""

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy.linalg import eigh
from scipy.signal import lfilter
from scipy.sparse import coo_matrix, csr_matrix, diags
from scipy.sparse.linalg import splu, spsolve


@dataclass
class Network:
    g: csr_matrix
    c: np.ndarray
    b: np.ndarray
    h: np.ndarray
    metadata: dict


def stack(x, y, thickness, conductivity, capacity, ga, cb):
    """Cell-centered orthogonal FV stack; z=0 is bottom, top attaches to bath."""
    x, y, dz, k, cv = [np.asarray(v, dtype=float) for v in (x, y, thickness, conductivity, capacity)]
    if (any(v.ndim != 1 or not np.all(np.isfinite(v)) for v in (x, y, dz, k, cv))
            or len(x)<2 or len(y)<2 or not len(dz) or len(k)!=len(dz) or len(cv)!=len(dz)
            or any(np.any(v <= 0) for v in (np.diff(x), np.diff(y), dz, k, cv))
            or not np.all(np.isfinite([ga, cb])) or min(ga, cb)<=0):
        raise ValueError('finite positive geometry, materials and sink required')
    dx, dy = np.diff(x), np.diff(y)
    nx, ny, nz = len(dx), len(dy), len(dz)
    ids = np.arange(nx*ny*nz).reshape(nz, ny, nx)
    count = ids.size+1
    rows, cols, vals = [], [], []
    diagonal = np.zeros(count)
    def edge(a, b, conductance):
        rows.extend([a, b]); cols.extend([b, a]); vals.extend([-conductance, -conductance])
        diagonal[a] += conductance; diagonal[b] += conductance
    for z in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                a = ids[z, iy, ix]
                if ix+1 < nx:
                    edge(a, ids[z, iy, ix+1], k[z]*dz[z]*dy[iy]/((dx[ix]+dx[ix+1])/2))
                if iy+1 < ny:
                    edge(a, ids[z, iy+1, ix], k[z]*dz[z]*dx[ix]/((dy[iy]+dy[iy+1])/2))
                area = dx[ix]*dy[iy]
                if z+1 < nz:
                    edge(a, ids[z+1, iy, ix], area/(dz[z]/(2*k[z])+dz[z+1]/(2*k[z+1])))
                else:
                    edge(a, count-1, 2*k[z]*area/dz[z])
    diagonal[-1] += ga
    rows.extend(range(count)); cols.extend(range(count)); vals.extend(diagonal)
    g = coo_matrix((vals, (rows, cols)), shape=(count, count)).tocsr()
    area = np.outer(dy, dx)
    c = np.r_[(cv[:, None, None]*dz[:, None, None]*area).ravel(), cb]
    return g, c, ids


def axis(features, pitch_um):
    if not np.isfinite(pitch_um) or pitch_um <= 0:
        raise ValueError('positive finite maximum pitch required')
    points = np.unique(features)
    return np.r_[np.concatenate([np.linspace(a, b, max(1, int(np.ceil((b-a)/pitch_um)))+1)[:-1]
                                 for a, b in zip(points[:-1], points[1:])]), points[-1]]*1e-6


def weights(centers, coordinate):
    if coordinate < centers[0]-1e-12 or coordinate > centers[-1]+1e-12:
        raise ValueError('sensor outside cell-center interpolation domain')
    nearest = int(np.argmin(abs(centers-coordinate)))
    if abs(centers[nearest]-coordinate) < 1e-12:
        return [(nearest, 1.)]
    hi = int(np.searchsorted(centers, coordinate))
    t = (coordinate-centers[hi-1])/(centers[hi]-centers[hi-1])
    return [(hi-1, 1-t), (hi, t)]


def build(geometry, group, ga, cb, pitch_um=500., bulk_cells=2, pad_cells=2):
    if group not in ('heatsink','heatsink_with_fan'):
        raise ValueError('unknown cooling group')
    if min(bulk_cells, pad_cells)<1 or int(bulk_cells)!=bulk_cells or int(pad_cells)!=pad_cells:
        raise ValueError('positive integer depth subdivisions required')
    heaters = geometry['heaters']
    side = geometry['die_side_um']
    x = axis([0., side]+[v for r in heaters for v in (r['x_um'],r['x_um']+r['width_um'])], pitch_um)
    y = axis([0., side]+[v for r in heaters for v in (r['y_um'],r['y_um']+r['height_um'])], pitch_um)
    materials = geometry['materials']['natural' if group=='heatsink' else 'fan']
    si, pad = materials['SILICON'], materials['SILICONE']
    dz = np.r_[geometry['active_silicon_um'], np.full(bulk_cells, geometry['bulk_silicon_um']/bulk_cells),
               np.full(pad_cells, geometry['thermal_pad_um']/pad_cells)]*1e-6
    k = np.r_[np.full(1+bulk_cells, si['conductivity_w_per_m_k']), np.full(pad_cells, pad['conductivity_w_per_m_k'])]
    cv = np.r_[np.full(1+bulk_cells, si['volumetric_capacity_j_per_m3_k']), np.full(pad_cells, pad['volumetric_capacity_j_per_m3_k'])]
    g, c, ids = stack(x, y, dz, k, cv, ga, cb)
    b = np.zeros((len(c),16))
    for heater in heaters:
        hx, hy, width, height = [heater[key]*1e-6 for key in ('x_um','y_um','width_um','height_um')]
        ax = np.maximum(0., np.minimum(x[1:],hx+width)-np.maximum(x[:-1],hx))
        ay = np.maximum(0., np.minimum(y[1:],hy+height)-np.maximum(y[:-1],hy))
        b[ids[0].ravel(),heater['power_index']] += np.outer(ay,ax).ravel()/(width*height)*heater['power_fraction']
    h = np.zeros((16,len(c)))
    for sensor,(sx,sy) in enumerate(np.array(geometry['sensors_xy_um'])*1e-6):
        for ix,wx in weights((x[:-1]+x[1:])/2,sx):
            for iy,wy in weights((y[:-1]+y[1:])/2,sy):
                h[sensor,ids[0,iy,ix]] += wx*wy
    if not np.allclose(b.sum(axis=0),1.,atol=1e-12,rtol=0) or not np.allclose(h.sum(axis=1),1.,atol=1e-12,rtol=0):
        raise ValueError('source or observation mapping does not conserve weights')
    meta=dict(kind='source_geometry_with_frozen_lumped_sink',group=group,node_count=len(c),
              nx=ids.shape[2],ny=ids.shape[1],nz=ids.shape[0],pitch_um=pitch_um,
              bulk_cells=bulk_cells,pad_cells=pad_cells,ga_w_per_k=ga,cb_j_per_k=cb,
              internal_capacity_j_per_k=float(c[:-1].sum()),thickness_m=dz.tolist(),
              x_edges_m=x.tolist(),y_edges_m=y.tolist(),layer_indices=ids.tolist(),
              source_weight_error=float(np.max(abs(b.sum(axis=0)-1))),
              sensor_weight_error=float(np.max(abs(h.sum(axis=1)-1))),
              physical_model_qualified=False)
    return Network(g,c,b,h,meta)


def initialize(network, power, first_temperature, uniform=False):
    mean = float(np.mean(first_temperature))
    if uniform:
        return np.full(len(network.c),mean)
    equilibrium = spsolve(network.g,network.b @ np.mean(power[:10],axis=0))
    return equilibrium+mean-float(np.mean(network.h @ equilibrium))


class Modal:
    """All modes of C dT/dt+G T=B P; only requested observations are retained."""
    def __init__(self, network):
        self.network = network
        started = perf_counter()
        scale = 1/np.sqrt(network.c)
        symmetric = network.g.toarray()*scale[:,None]*scale[None,:]
        self.rates,q = eigh(symmetric,overwrite_a=True,check_finite=False,driver='evd')
        if self.rates.min()<=0:
            raise ValueError('unanchored/unstable network')
        self.w = q*scale[:,None]
        self.bw = network.b.T @ self.w
        self.wh = self.w.T @ network.h.T
        self.storage = self.w.T @ network.c
        self.loss = self.w.T @ np.asarray(network.g.sum(axis=0)).ravel()
        groups = network.metadata.get('layer_indices', [])
        if groups:
            membership=np.zeros((len(network.c),len(groups)+1))
            for i,ids in enumerate(groups):
                membership[np.asarray(ids).ravel(),i]=1
            membership[-1,-1]=1
            self.layer_storage=self.w.T @ (network.c[:,None]*membership)
            self.layer_flow=self.w.T @ (network.g.T @ membership)
            self.layer_inputs=network.b.T @ membership
        else:
            self.layer_storage=self.layer_flow=self.layer_inputs=None
        self.setup_seconds = perf_counter()-started

    def run(self,power,initial,dt=.1,chunk_size=2048):
        p,initial = np.asarray(power,dtype=float),np.asarray(initial,dtype=float)
        n = self.network
        if (p.ndim!=2 or p.shape[1]!=n.b.shape[1] or not len(p) or initial.shape!=n.c.shape
                or not np.isfinite(dt) or dt<=0 or not np.all(np.isfinite(p)) or not np.all(np.isfinite(initial))):
            raise ValueError('invalid transient input')
        rate = self.rates
        decay = np.exp(-rate*dt)
        b = -np.expm1(-rate*dt)/rate
        x = rate*dt
        d = np.empty_like(rate)
        small=x<1e-3
        d[~small]=(dt-b[~small])/rate[~small]
        xs=x[small]; d[small]=dt**2*(.5-xs/6+xs**2/24-xs**3/120+xs**4/720)
        z = self.w.T @ (n.c*initial)
        initial_z = z.copy()
        y = np.empty((len(p),n.h.shape[0]))
        removed=0.; max_residual=0.; max_normalized=0.; max_layer_error=0.
        started=perf_counter()
        for start in range(0,len(p),chunk_size):
            block = p[start:start+chunk_size]
            u = block @ self.bw
            ends = np.empty_like(u)
            for j in range(len(z)):
                ends[:,j],_ = lfilter([b[j]],[1.,-decay[j]],u[:,j],zi=[decay[j]*z[j]])
            begins = np.vstack((z,ends[:-1]))
            interval_removed = (b*begins+d*u) @ self.loss
            interval_storage = (np.expm1(-x)*begins+b*u) @ self.storage
            interval_input = block @ n.b.sum(axis=0)*dt
            if self.layer_storage is not None:
                layer_error=block @ self.layer_inputs*dt-(np.expm1(-x)*begins+b*u) @ self.layer_storage-(b*begins+d*u) @ self.layer_flow
                max_layer_error=max(max_layer_error,float(np.abs(layer_error).max()))
            residual = interval_input-interval_storage-interval_removed
            removed += float(interval_removed.sum())
            max_residual=max(max_residual,float(np.abs(residual).max()))
            max_normalized=max(max_normalized,float(np.max(np.abs(residual)/np.maximum(1.,np.abs(interval_input)))))
            y[start:start+len(block)] = ends @ self.wh
            z = ends[-1].copy()
        supplied = float((p @ n.b.sum(axis=0)).sum()*dt)
        stored = float((z-initial_z) @ self.storage)
        residual = supplied-stored-removed
        return y,dict(interval_count=len(p),input_energy_j=supplied,storage_change_j=stored,
                      removed_heat_j=removed,energy_error_j=residual,
                      normalized_energy_error=abs(residual)/max(1.,abs(supplied)),
                      max_interval_energy_error_j=max_residual,max_normalized_interval_energy_error=max_normalized,
                      max_layer_interval_energy_error_j=max_layer_error if self.layer_storage is not None else None,
                      numerical_energy_screen=bool(abs(residual)/max(1.,abs(supplied))<1e-7 and max_normalized<1e-7),
                      fastest_time_constant_s=float(1/rate.max()),slowest_time_constant_s=float(1/rate.min()),
                      propagation_seconds=perf_counter()-started,all_modes_retained=len(rate))


def backward_euler(network,power,initial,dt):
    factor=splu((network.g+diags(network.c/dt)).tocsc())
    theta=np.asarray(initial).copy()
    result=[]
    for p in power:
        theta=factor.solve(network.b @ p+network.c/dt*theta)
        result.append(network.h @ theta)
    return np.asarray(result)
