"""Estimate peak and bound source-weighted temperature on a geometry-specific FV operator."""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from ..model import parse_case
from ..package import assemble_package, checked_solution
from ..power import rasterize
from .thermal import AMBIENT_C, thermal_case_data


def projected_field(problem, layout, gap_um=100, resolution=64, block_mm=4.):
    case = parse_case(thermal_case_data(problem,layout,gap_um,resolution),node_limit=450000)
    watts,_ = rasterize(case)
    a,b,sink,_,ids,power_z = assemble_package(case,watts)
    z,y,x = np.where(ids>=0)
    ex,ey = np.asarray(case.mesh.x_edges_mm), np.asarray(case.mesh.y_edges_mm)
    gx = ((ex[:-1]+ex[1:])/(2*block_mm)).astype(int)
    gy = ((ey[:-1]+ey[1:])/(2*block_mm)).astype(int)
    index = ((z*(gy.max()+1)+gy[y])*(gx.max()+1)+gx[x])
    _, group = np.unique(index,return_inverse=True)
    basis = sparse.csr_matrix((np.ones(len(b)),(ids[z,y,x],group)))
    reduced = (basis.T@a@basis).tocsc()
    loads = basis.T@b
    theta = spsolve(reduced,loads)
    checked_solution(reduced,loads,basis.T@sink,theta)
    v = basis@theta
    active = ids[power_z]>=0
    rise = np.full(active.shape,np.nan)
    rise[active] = v[ids[power_z][active]]
    lower = AMBIENT_C+(2*b@v-v@(a@v))/b.sum()
    return dict(estimated_peak_c=AMBIENT_C+float(np.nanmax(rise)),lower_peak_c=float(lower)-1e-7,
                reduced_nodes=len(theta),full_nodes=len(b)),rise,(ex,ey)
