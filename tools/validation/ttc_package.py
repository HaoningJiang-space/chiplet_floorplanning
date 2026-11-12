"""Conforming 3-D FV diagnostic of a source-defined TTC pad, base and fins.

This is an independent finite-volume construction from geometry and physical
equations, not a translation of the upstream Modelica implementation.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix, diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import cg, splu

from .ttc_geometry import number
from .ttc_separable import planar_mappings
from .ttc_spatial import weights


@dataclass
class Block:
    name: str
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    k: float
    ids: np.ndarray
    capacity: np.ndarray


class Assembly:
    def __init__(self):
        self.blocks = []
        self.edges = []
        self.anchors = []
        self.interfaces = []
        self.count = 0

    def edge(self, a, b, conductance):
        a, b, g = np.broadcast_arrays(a, b, conductance)
        if np.any(g <= 0) or not np.all(np.isfinite(g)) or np.any(a == b):
            raise ValueError('finite positive conductance between distinct nodes required')
        self.edges.append((a.ravel(), b.ravel(), g.ravel()))

    def anchor(self, ids, conductance):
        ids, g = np.broadcast_arrays(ids, conductance)
        if np.any(g <= 0) or not np.all(np.isfinite(g)):
            raise ValueError('finite positive boundary conductance required')
        self.anchors.append((ids.ravel(), g.ravel()))

    def block(self, name, x, y, z, k, cv):
        x, y, z = [np.asarray(v, dtype=float) for v in (x, y, z)]
        if (any(v.ndim != 1 or len(v) < 2 or not np.all(np.isfinite(v)) or np.any(np.diff(v) <= 0)
                for v in (x, y, z)) or not np.all(np.isfinite([k, cv])) or min(k, cv) <= 0):
            raise ValueError('finite increasing axes and positive material required')
        dx, dy, dz = map(np.diff, (x, y, z))
        shape = (len(dz), len(dy), len(dx))
        ids = np.arange(self.count, self.count+np.prod(shape), dtype=np.int32).reshape(shape)
        self.count += ids.size
        capacity = cv*dz[:, None, None]*dy[None, :, None]*dx[None, None, :]
        self.edge(ids[:, :, :-1], ids[:, :, 1:],
                  k*dz[:, None, None]*dy[None, :, None]/((dx[:-1]+dx[1:])[None, None, :]/2))
        self.edge(ids[:, :-1, :], ids[:, 1:, :],
                  k*dz[:, None, None]*dx[None, None, :]/((dy[:-1]+dy[1:])[None, :, None]/2))
        self.edge(ids[:-1], ids[1:],
                  k*dy[None, :, None]*dx[None, None, :]/((dz[:-1]+dz[1:])[:, None, None]/2))
        block = Block(name, x, y, z, k, ids, capacity)
        self.blocks.append(block)
        return block

    def join(self, lower, upper):
        if abs(lower.z[-1]-upper.z[0]) > 1e-12:
            raise ValueError('material faces must meet at the same z')
        ax, bx, dx = matching_overlap(lower.x, upper.x)
        ay, by, dy = matching_overlap(lower.y, upper.y)
        area = np.outer(dy, dx)
        resistance_area = np.diff(lower.z)[-1]/(2*lower.k) + np.diff(upper.z)[0]/(2*upper.k)
        a = lower.ids[-1, ay[:, None], ax[None, :]]
        b = upper.ids[0, by[:, None], bx[None, :]]
        conductance = area/resistance_area
        self.edge(a, b, conductance)
        self.interfaces.append(dict(name=lower.name+'->'+upper.name,
                                    area_m2=float(area.sum()), a=a.ravel(), b=b.ravel(),
                                    g=conductance.ravel()))

    def matrix(self):
        a = np.concatenate([e[0] for e in self.edges])
        b = np.concatenate([e[1] for e in self.edges])
        g = np.concatenate([e[2] for e in self.edges])
        loss = np.zeros(self.count)
        for ids, coefficient in self.anchors:
            np.add.at(loss, ids, coefficient)
        diagonal = np.bincount(a, weights=g, minlength=self.count) + np.bincount(b, weights=g, minlength=self.count) + loss
        rows = np.concatenate((a, b, np.arange(self.count)))
        cols = np.concatenate((b, a, np.arange(self.count)))
        matrix = coo_matrix((np.concatenate((-g, -g, diagonal)), (rows, cols)), shape=(self.count, self.count)).tocsr()
        matrix.sum_duplicates(); matrix.sort_indices()
        if connected_components(matrix, directed=False, return_labels=False) != 1 or not np.any(loss > 0):
            raise ValueError('network must be connected and anchored')
        capacity = np.concatenate([block.capacity.ravel() for block in self.blocks])
        audit = dict(node_count=self.count, nonzeros=matrix.nnz,
                     symmetry_error=float(abs(matrix-matrix.T).max()),
                     row_sum_boundary_error_w_per_k=float(np.max(abs(matrix @ np.ones(self.count)-loss))),
                     total_capacity_j_per_k=float(capacity.sum()), min_capacity_j_per_k=float(capacity.min()),
                     total_boundary_conductance_w_per_k=float(loss.sum()),
                     block_capacities_j_per_k={block.name:float(block.capacity.sum()) for block in self.blocks},
                     interface_areas_m2={i['name']:i['area_m2'] for i in self.interfaces})
        return matrix, loss, capacity, audit


def matching_overlap(a, b):
    """Reject nonorthogonal, nonmatching interfaces rather than hide TPFA error."""
    overlap = np.minimum(a[1:, None], b[None, 1:]) - np.maximum(a[:-1, None], b[None, :-1])
    ia, ib = np.nonzero(overlap > 1e-14)
    length = overlap[ia, ib]
    if (not len(length) or np.any(abs(length-np.diff(a)[ia]) > 1e-12)
            or np.any(abs(length-np.diff(b)[ib]) > 1e-12)
            or np.any(abs((a[ia]+a[ia+1])/2-(b[ib]+b[ib+1])/2) > 1e-12)):
        raise ValueError('interface requires matching orthogonal cell faces')
    return ia, ib, length


def source_boundary(root):
    lock = json.loads(Path('tools/ttc-package-boundary.lock.json').read_text())
    for record in lock['files']:
        if hashlib.sha256((root/record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('boundary source hash mismatch')
    sink = (root/'ice3/heatsink_plugin/heatsinks/HS483/HS483.mo').read_text()
    names = ('baseLength', 'baseWidth', 'baseHeight', 'baseCols', 'finHeight', 'finThickness',
             'k', 'rho', 'cp', 'fanFlowRateCoefficient', 'operatingPoint', 'fanArea', 'c0', 'c1', 'c2')
    values = {key:number(sink, key) for key in names}
    # Exact SI conversion, explicitly distinguished from the upstream rounded 9.55.
    values['fan_velocity_m_per_s'] = 2700*2*np.pi/60*values['fanFlowRateCoefficient']*values['operatingPoint']/values['fanArea']
    velocity = values['fan_velocity_m_per_s']
    if not 1 <= velocity <= 4.1:
        raise ValueError('fan velocity outside source correlation domain')
    values['fan_htc_w_per_m2_k'] = .8793*(values['c0']+values['c1']*velocity+values['c2']*velocity**2)
    values['natural_htc_w_per_m2_k'] = 2.8
    values['full_pad_side_m'] = .027
    values['source_lock_sha256'] = hashlib.sha256(Path('tools/ttc-package-boundary.lock.json').read_bytes()).hexdigest()
    values['fin_position_measured'] = False
    return values


def shared_axis(features, die_bounds, die_pitch, outside_pitch):
    points = np.unique(features)
    parts = []
    for low, high in zip(points[:-1], points[1:]):
        pitch = die_pitch if die_bounds[0]-1e-12 <= (low+high)/2 <= die_bounds[1]+1e-12 else outside_pitch
        parts.append(np.linspace(low, high, max(1, int(np.ceil((high-low)/pitch)))+1)[:-1])
    return np.r_[np.concatenate(parts), points[-1]]


def crop(axis, low, high):
    result = axis[(axis >= low-1e-12) & (axis <= high+1e-12)]
    if abs(result[0]-low) > 1e-12 or abs(result[-1]-high) > 1e-12:
        raise ValueError('footprint edge missing from conforming partition')
    return result


def build(geometry, boundary, group, level, model):
    if group not in ('heatsink', 'heatsink_with_fan') or model not in ('U', 'C', 'P') or level not in range(5):
        raise ValueError('unknown package configuration')
    factor = 2**level
    na, nb, npad, ncu, nfin = factor, 2*factor, 2*factor, 2*factor, 4*factor
    size = geometry['die_side_um']*1e-6
    side = boundary['baseLength']
    if boundary['baseWidth'] != side:
        raise ValueError('current fixture expects a square base')
    dlo, dhi = (side-size)/2, (side+size)/2
    plo, phi = (side-boundary['full_pad_side_m'])/2, (side+boundary['full_pad_side_m'])/2
    centers = (np.arange(int(boundary['baseCols']))+.5)*side/boundary['baseCols']
    fin_edges = np.ravel(np.column_stack((centers-boundary['finThickness']/2, centers+boundary['finThickness']/2)))
    common = [0., side, dlo, dhi, plo, phi]
    xf = common+fin_edges.tolist()+[dlo+h[key]*1e-6+offset for h in geometry['heaters']
                                    for key, offset in (('x_um', 0.), ('x_um', h['width_um']*1e-6))]
    yf = common+[dlo+h[key]*1e-6+offset for h in geometry['heaters']
                 for key, offset in (('y_um', 0.), ('y_um', h['height_um']*1e-6))]
    x = shared_axis(xf, (dlo, dhi), 500e-6/factor, 2000e-6/factor)
    y = shared_axis(yf, (dlo, dhi), 500e-6/factor, 2000e-6/factor)
    dx, dy = crop(x, dlo, dhi), crop(y, dlo, dhi)
    zactive = np.linspace(0., geometry['active_silicon_um']*1e-6, na+1)
    zbulk = np.linspace(zactive[-1], zactive[-1]+geometry['bulk_silicon_um']*1e-6, nb+1)
    zpad = np.linspace(zbulk[-1], zbulk[-1]+geometry['thermal_pad_um']*1e-6, npad+1)
    material = geometry['materials']['natural' if group == 'heatsink' else 'fan']
    si, pad = material['SILICON'], material['SILICONE']
    assembly = Assembly()
    die = assembly.block('die', dx, dy, np.r_[zactive, zbulk[1:]], si['conductivity_w_per_m_k'], si['volumetric_capacity_j_per_m3_k'])
    px, py = (crop(x, plo, phi), crop(y, plo, phi)) if model == 'P' else (dx, dy)
    pad_block = assembly.block('pad', px, py, zpad, pad['conductivity_w_per_m_k'], pad['volumetric_capacity_j_per_m3_k'])
    assembly.join(die, pad_block)
    if model == 'U':
        area = np.outer(np.diff(py), np.diff(px))
        assembly.anchor(pad_block.ids[-1], area/(np.diff(zpad)[-1]/(2*pad_block.k)))
    else:
        zbase = np.linspace(zpad[-1], zpad[-1]+boundary['baseHeight'], ncu+1)
        copper = assembly.block('base', x, y, zbase, boundary['k'], boundary['rho']*boundary['cp'])
        assembly.join(pad_block, copper)
        htc = boundary['natural_htc_w_per_m2_k'] if group == 'heatsink' else boundary['fan_htc_w_per_m2_k']
        zfin = np.linspace(zbase[-1], zbase[-1]+boundary['finHeight'], nfin+1)
        for i, center in enumerate(centers):
            fx = crop(x, center-boundary['finThickness']/2, center+boundary['finThickness']/2)
            fin = assembly.block('fin_'+str(i), fx, y, zfin, boundary['k'], boundary['rho']*boundary['cp'])
            assembly.join(copper, fin)
            area = np.outer(np.diff(zfin), np.diff(y))
            assembly.anchor(fin.ids[:, :, 0], area/(1/htc+np.diff(fx)[0]/(2*fin.k)))
            assembly.anchor(fin.ids[:, :, -1], area/(1/htc+np.diff(fx)[-1]/(2*fin.k)))
    g, loss, c, audit = assembly.matrix()
    bp, hp = planar_mappings(geometry, dx-dlo, dy-dlo)
    # Sparse source/sensor mappings avoid a dense N x 16 allocation.
    by, bx, channel = np.nonzero(bp)
    rows, cols, values = [], [], []
    for iz in range(na):
        rows.extend(die.ids[iz, by, bx].tolist()); cols.extend(channel.tolist()); values.extend((bp[by, bx, channel]/na).tolist())
    b = coo_matrix((values, (rows, cols)), shape=(len(c), 16)).tocsr()
    sensor, hy, hx = np.nonzero(hp)
    rows, cols, values = [], [], []
    for iz, weight in weights((die.z[:-1]+die.z[1:])/2, zactive[-1]/2):
        rows.extend(sensor.tolist()); cols.extend(die.ids[iz, hy, hx].tolist()); values.extend((hp[sensor, hy, hx]*weight).tolist())
    h = coo_matrix((values, (rows, cols)), shape=(16, len(c))).tocsr()
    if not np.allclose(np.asarray(b.sum(axis=0)), 1., atol=1e-12, rtol=0) or not np.allclose(np.asarray(h.sum(axis=1)), 1., atol=1e-12, rtol=0):
        raise ValueError('power or observation mapping failed')
    audit.update(group=group, model=model, level=level, die_nx=len(dx)-1, die_ny=len(dy)-1,
                 base_nx=len(x)-1, base_ny=len(y)-1, physical_model_qualified=False,
                 die_xy_edges_m=[(dx-dlo).tolist(), (dy-dlo).tolist()], source_boundary=boundary)
    return g, loss, b, h, assembly, audit


def solve(g, loss, b, h, assembly, method='amg', progress=None):
    """Solve 16 unit-source problems with checked physical residuals."""
    start = perf_counter()
    if method == 'direct':
        factor = splu(g.tocsc())
    elif method == 'amg':
        import pyamg
        scaling = 1/np.sqrt(g.diagonal())
        scaled = (diags(scaling) @ g @ diags(scaling)).tocsr()
        hierarchy = pyamg.ruge_stuben_solver(scaled,
            presmoother=('gauss_seidel', {'sweep':'symmetric'}),
            postsmoother=('gauss_seidel', {'sweep':'symmetric'}))
        preconditioner = hierarchy.aspreconditioner(cycle='V')
    else:
        raise ValueError('unknown solver')
    setup = perf_counter()-start
    observations, records = [], []
    for channel in range(b.shape[1]):
        rhs = b[:, channel].toarray().ravel()
        iterations = [0]
        def callback(_):
            iterations[0] += 1
        started = perf_counter()
        if method == 'direct':
            theta = factor.solve(rhs)
        else:
            answer, info = cg(scaled, scaling*rhs, M=preconditioner, rtol=1e-11, atol=0., maxiter=600, callback=callback)
            if info != 0:
                raise ValueError('CG did not converge: '+str(info))
            theta = scaling*answer
        residual = g @ theta-rhs
        heat_error = abs(loss @ theta-rhs.sum())
        relative_residual = np.linalg.norm(residual)/np.linalg.norm(rhs)
        if heat_error > 1e-7 or relative_residual > 1e-7 or theta.min() < -1e-8:
            raise ValueError('steady residual/heat balance/passivity screen failed')
        observation = np.asarray(h @ theta).ravel()
        observations.append(observation)
        interfaces = {i['name']:float(i['g'] @ (theta[i['a']]-theta[i['b']])) for i in assembly.interfaces}
        record = dict(channel=channel, iterations=iterations[0], seconds=perf_counter()-started,
                      max_node_residual_w=float(np.max(abs(residual))), relative_residual=float(relative_residual),
                      boundary_heat_error_w=float(heat_error), minimum_temperature_rise_k=float(theta.min()),
                      interface_heat_w=interfaces,
                      max_block_equation_residual_w=max(float(abs(residual[block.ids.ravel()].sum())) for block in assembly.blocks))
        records.append(record)
        if progress is not None:
            progress(record)
    return np.array(observations).T, dict(method=method, setup_seconds=setup, total_seconds=perf_counter()-start, channels=records)
