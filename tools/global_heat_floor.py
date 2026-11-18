"""Variational peak-temperature floors for all translations on a fixed carrier."""
import numpy as np
from scipy.sparse import bmat, diags, kron
from scipy.sparse.linalg import spsolve


def knots(limit, edges, refinement):
    """Quarter-domain mesh in metres, exactly aligned at every supplied edge."""
    anchors = sorted({0., limit, *(x for x in edges if 0 < x < limit)})
    values = [0.]
    for start, end in zip(anchors, anchors[1:]):
        intervals = max(1, int(np.ceil((end-start)/0.008))) * refinement
        values.extend(np.linspace(start, end, intervals+1)[1:])
    return np.array(values)


def line_forms(coords, end):
    """Integrate the linear hat mass and derivative matrices up to an edge."""
    dx = np.diff(coords)
    active = coords[1:] <= end + 1e-12
    m = dx * active / 6
    k = active / dx
    mass = diags([m, 2*(np.r_[0,m]+np.r_[m,0]), m], [-1,0,1], format='csr')
    stiff = diags([-k, np.r_[0,k]+np.r_[k,0], -k], [-1,0,1], format='csr')
    return mass, stiff


def planar_forms(x, y, extent):
    mx, kx = line_forms(x, extent[0])
    my, ky = line_forms(y, extent[1])
    mass = kron(my, mx, format='csr')
    stiff = kron(my, kx, format='csr') + kron(ky, mx, format='csr')
    return mass, stiff


def square_integral(a, dx, dy):
    """Exact integral of a bilinear field squared, with positive Gauss weights."""
    value = np.zeros_like(a[:-1, :-1])
    for u in (0.5-0.5/np.sqrt(3), 0.5+0.5/np.sqrt(3)):
        lower = (1-u)*a[:-1,:-1] + u*a[:-1,1:]
        upper = (1-u)*a[1:,:-1] + u*a[1:,1:]
        for v in (0.5-0.5/np.sqrt(3), 0.5+0.5/np.sqrt(3)):
            value += ((1-v)*lower + v*upper)**2/4
    return float(dy @ value @ dx)


def derivative_integral(a, x, y):
    dx, dy = np.diff(x), np.diff(y)
    gx = np.diff(a, axis=1)/dx
    gy = np.diff(a, axis=0)/dy[:,None]
    return float(dy @ ((gx[:-1]**2 + gx[:-1]*gx[1:] + gx[1:]**2 +
                        gy[:,:-1]**2 + gy[:,:-1]*gy[:,1:] + gy[:,1:]**2)/3) @ dx)


def trial(stack, power_z, h, half_die, refinement):
    """Carrier isothermal trial or a translated, compactly supported single-die trial."""
    local = half_die is not None
    if local:
        limit = max(0.100, max(half_die)+0.055)
        extents = [(limit, limit)]*len(stack)
        def local_grid(half):
            return knots(limit, (half/2, half, half+.001, half+.003, half+.008, half+.020), refinement)
        x, y = map(local_grid, half_die)
    else:
        extents = [s['extent_m'] for s in stack]
        x, y = [knots(max(e[axis] for e in extents), [e[axis] for e in extents], refinement)
                for axis in (0,1)]
    forms = {e:planar_forms(x, y, e) for e in set(extents)}
    n, cells = len(stack), len(x)*len(y)
    blocks = [[None]*n for _ in stack]
    active = np.zeros((n,len(y),len(x)), dtype=bool)
    widths = []
    for z,(s,extent) in enumerate(zip(stack, extents)):
        nx = int(np.sum(x <= extent[0]+1e-12))
        ny = int(np.sum(y <= extent[1]+1e-12))
        widths.append((nx,ny))
        active[z,:ny,:nx] = True
        blocks[z][z] = (s['k']*s['t_m'])*forms[extent][1]
    contacts = []
    for z,(a,b) in enumerate(zip(stack, stack[1:])):
        extent = tuple(min(i,j) for i,j in zip(extents[z],extents[z+1]))
        g = 1/(a['t_m']/(2*a['k']) + a['contact_above_m2k_w'] + b['t_m']/(2*b['k']))
        contacts.append(g)
        coupling = g * forms[extent][0]
        blocks[z][z] += coupling
        blocks[z+1][z+1] += coupling
        blocks[z][z+1] = blocks[z+1][z] = -coupling
    sink = 1/(1/h+stack[-1]['t_m']/(2*stack[-1]['k']))
    blocks[-1][-1] += sink*forms[extents[-1]][0]
    matrix = bmat(blocks, format='csr')
    free = active.copy()
    values = np.zeros(active.shape)
    rhs = np.zeros(n*cells)
    if local:
        mx,_ = line_forms(x,half_die[0])
        my,_ = line_forms(y,half_die[1])
        load = np.outer(np.asarray(my.sum(axis=1)).ravel(), np.asarray(mx.sum(axis=1)).ravel())
        load /= 4*half_die[0]*half_die[1]
        assert abs(load.sum()-.25) < 1e-10
        rhs[power_z*cells:(power_z+1)*cells] = load.ravel()
        free[:,-1,:] = free[:,:,-1] = False
    else:
        free[power_z] = False
        values[power_z] = active[power_z]
    keep = free.ravel()
    reduced_rhs = (rhs-matrix@values.ravel())[keep]
    values.ravel()[keep] = spsolve(matrix[keep][:,keep].tocsc(), reduced_rhs,
                                   permc_spec='MMD_AT_PLUS_A')
    # Re-evaluate the actual trial by element integrals, independent of sparse assembly.
    lateral, vertical = [], []
    for z,(nx,ny) in enumerate(widths):
        s = stack[z]
        lateral.append(s['k']*s['t_m']*derivative_integral(values[z,:ny,:nx], x[:nx], y[:ny]))
        if z < n-1:
            nx, ny = min(nx,widths[z+1][0]), min(ny,widths[z+1][1])
            difference = values[z,:ny,:nx]-values[z+1,:ny,:nx]
            vertical.append(contacts[z]*square_integral(difference,np.diff(x[:nx]),np.diff(y[:ny])))
    nx, ny = widths[-1]
    boundary = sink*square_integral(values[-1,:ny,:nx], np.diff(x[:nx]), np.diff(y[:ny]))
    energy = 4*(sum(lateral)+sum(vertical)+boundary)
    assert energy > 0 and min([*lateral,*vertical,boundary]) >= 0
    algebraic = 4*(values.ravel() @ (matrix @ values.ravel()))
    assert abs(energy-algebraic) <= 1e-7 * energy
    work = 1.0
    if local:
        nx,ny = int(sum(x<=half_die[0]+1e-12)),int(sum(y<=half_die[1]+1e-12))
        v = values[power_z,:ny,:nx]
        mean = (v[:-1,:-1]+v[:-1,1:]+v[1:,:-1]+v[1:,1:])/4
        work = float(np.diff(y[:ny]) @ mean @ np.diff(x[:nx]) / np.prod(half_die))
        assert work > 0 and abs(work-4*rhs@values.ravel()) < 1e-9
    return dict(bound_k_w=(work**2/energy)*(1-1e-7), energy=energy, work=work,
                energy_convention='unit_watt_source' if local else 'unit_kelvin_clamp',
                planar_nodes=int(cells), assembly_relative_error=abs(energy-algebraic)/energy)


def stack_spec(data):
    cfg = data['thermal']
    assert cfg['bottom_h_w_m2k']==0 and cfg['top_h_w_m2k']>0
    out = []
    for s in cfg['layers']:
        assert s['footprint']=='rectangle' and 'conductivity_xyz_w_mk' not in s
        rect = s['rect_mm']
        assert all(abs(rect[axis]+rect[side]/2-data['package_mm'][side]/2)<1e-8
                   for axis,side in [('x','width'),('y','height')])
        materials = s.get('die_materials',{}).values()
        assert all('conductivity_xyz_w_mk' not in m for m in materials)
        out.append(dict(id=s['id'], t_m=s['thickness_mm']/1000,
                        k=max([s['conductivity_w_mk'],*(m['conductivity_w_mk'] for m in materials)]),
                        contact_above_m2k_w=s.get('contact_resistance_above_m2k_w',0),
                        extent_m=tuple(rect[side]/2000 for side in ('width','height'))))
    return out, [s['id'] for s in out].index(cfg['power_layer'])


def floor_for_case(problem, data):
    stack,z = stack_spec(data)
    cfg = data['thermal']
    h = cfg['top_h_w_m2k']
    sizes = [tuple(sorted(s/2e6)) for s in problem.size_um]
    carrier = [trial(stack,z,h,None,r) for r in (1,2)]
    unit = {size:[trial(stack,z,h,size,r) for r in (1,2)] for size in sorted(set(sizes))}
    for pair in [carrier,*unit.values()]:
        assert pair[1]['bound_k_w'] >= pair[0]['bound_k_w'] - 1e-8
    local = [float(p*unit[size][-1]['bound_k_w']) for p,size in zip(problem.power_w,sizes)]
    shared = float(problem.power_w.sum()*carrier[-1]['bound_k_w'])
    lower = cfg['ambient_c']+max([shared,*local])
    return dict(ambient_c=cfg['ambient_c'],h_w_m2k=h,stack=stack,carrier_trials=carrier,
                die_trials=[dict(half_sides_m=s, trials=t) for s,t in unit.items()],
                dies=[dict(name=name,power_w=float(p),half_sides_m=s,self_floor_k=q)
                      for name,p,s,q in zip(problem.names,problem.power_w,sizes,local)],
                carrier_floor_k=shared,self_floor_k=max(local),floor_c=np.floor(100*lower)/100)
