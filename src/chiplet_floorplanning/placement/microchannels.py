"""Single-phase parallel grooves with finite headers, wall conduction and axial advection."""
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.optimize import brentq
from scipy.sparse.linalg import spsolve


@dataclass(frozen=True)
class Channels:
    count: int = 144
    length_m: float = .064
    width_m: float = .000231
    depth_m: float = .000713
    pitch_m: float = .000467
    header_side_m: float = .024

    @property
    def diameter_m(self):
        return 2*self.width_m*self.depth_m/(self.width_m+self.depth_m)


RHO = 994.0       # kg/m³, nominal board water properties at 35 °C
CP = 4179.0       # J/(kg K)
WATER_K = .623    # W/(m K)
MU = .000719      # Pa s


def duct_resistance(length, width, depth, viscosity):
    """Fully developed rectangular Poiseuille solution, Pa s/m³."""
    a, b = sorted((width, depth))
    odd = np.arange(1., 50., 2.)
    correction = 1 - 192*a/(np.pi**5*b)*np.sum(np.tanh(odd*np.pi*b/(2*a))/odd**5)
    return 12*viscosity*length/(b*a**3*correction)


def hydraulics(plate, pump_w, reverse=False):
    """Fixed hydraulic power at the two external ports of a Z manifold."""
    n = plate.count
    segment = np.arange(n-1)[:, None]
    branch = np.arange(n)[None, :]
    left = (branch > segment).astype(float)
    right = (branch <= segment).astype(float)
    supply, ret = (right, left) if reverse else (left, right)
    rh = duct_resistance(plate.pitch_m, plate.header_side_m, plate.header_side_m, MU)
    rc = duct_resistance(plate.length_m, plate.width_m, plate.depth_m, MU)
    header = rh*(supply.T@supply + ret.T@ret)
    area = plate.width_m*plate.depth_m
    minor = .5*RHO/area**2
    # At prescribed port pressure invert each branch loss, then update the small
    # but nonzero header loss. Confirm the reconstructed port pressures after convergence.
    def flows(pressure):
        q = np.zeros(n)
        for _ in range(30):
            dp = pressure-header@q
            if np.any(dp <= 0):
                raise ValueError('header loss too large for this parallel-flow iteration')
            updated = 2*dp/(rc+np.sqrt(rc**2+4*minor*dp))
            if np.max(abs(updated-q)) <= 1e-12*updated.max():
                return updated
            q = updated
        raise ArithmeticError('pressure iteration did not converge')
    ideal = np.sqrt(rc*pump_w/n)
    high = 2*ideal + minor*(pump_w/(n*ideal))**2
    pressure = brentq(lambda d: d*flows(d).sum()-pump_w, ideal*.1, high)
    q = flows(pressure)
    branch_drop = rc*q + minor*q**2
    qs, qr = supply@q, ret@q
    path = supply.T@(rh*qs) + branch_drop + ret.T@(rh*qr)
    loss = np.dot(branch_drop,q) + rh*(qs@qs+qr@qr)
    # In physical branch order one header loses branch flow and the other gains it.
    falling, rising = (qr,qs) if reverse else (qs,qr)
    supply_balance = -np.diff(np.r_[q.sum(),falling,0.])-q
    return_balance = np.diff(np.r_[0.,rising,q.sum()])-q
    node_error = max(np.max(abs(supply_balance)),np.max(abs(return_balance)))
    return q, dict(pressure_pa=float(pressure), flow_lpm=float(q.sum()*60000),
                   supply_port_branch=(n-1 if reverse else 0),
                   branch_lpm=(q*60000).tolist(), branch_drop_pa=branch_drop.tolist(),
                   hydraulic_w=float(pressure*q.sum()), dissipation_w=float(loss),
                   max_path_residual_pa=float(np.max(abs(path-pressure))),
                   max_node_mass_residual_kg_s=float(RHO*node_error),
                   max_branch_re=float((q/area).max()*plate.diameter_m*RHO/MU),
                   max_header_re=float(q.sum()*RHO/(plate.header_side_m*MU)))


def wall_conductance(plate, q, edges_m, reverse, solid_k, roof_half_m,
                     *, viscosity=MU, rho=RHO, cp=CP, liquid_k=WATER_K):
    """Per pitch area U, W/(m² K), from developing flow and two adiabatic-tip fins."""
    x = np.asarray(edges_m)
    path = x[-1] - x[::-1] if reverse else x-x[0]
    d = plate.diameter_m
    aspect = min(plate.width_m,plate.depth_m)/max(plate.width_m,plate.depth_m)
    nu_fd = 8.235*np.polynomial.polynomial.polyval(aspect,[1,-2.0421,3.0853,-2.4765,1.0578,-.1861])
    re = q*rho*d/(plate.width_m*plate.depth_m*viscosity)
    pr = cp*viscosity/liquid_k
    # x times mean Nu; differencing yields a finite segment-average coefficient
    # even on the first segment. The cubic blend is an engineering closure.
    x_nu = np.cbrt((nu_fd*path)**3 + 1.86**3 * re[:,None]*pr*d*path**2)
    h = np.diff(x_nu,axis=1)/np.diff(path)*liquid_k/d
    if reverse:
        h = h[:, ::-1]
    rib = plate.pitch_m-plate.width_m
    md = plate.depth_m*np.sqrt(2*h/(solid_k*rib))
    effective_width = plate.width_m + 2*plate.depth_m*np.tanh(md)/md
    return 1/(roof_half_m/solid_k + plate.pitch_m/(h*effective_width))


def conjugate(solid, load, wall_ids, x_m, y_m, plate, q, reverse, solid_k, roof_half_m,
              *, viscosity=MU, rho=RHO, cp=CP, liquid_k=WATER_K):
    """Couple an insulated solid FV matrix to channel segments on its grooved face.

    Each branch has its own fluid unknown for each x segment. Wall conductance
    is apportioned by the solid cells' overlaps with its pitch; all heat terms
    enter solid and fluid with opposite signs. Temperatures returned are rises.
    """
    n, nx = plate.count, len(x_m)-1
    end = np.arange(n+1)*plate.pitch_m
    if not (np.isclose(y_m[-1]-y_m[0], end[-1]) and np.isclose(x_m[-1]-x_m[0],plate.length_m)):
        raise ValueError('cooled solid face does not cover the declared channel array')
    y = y_m-y_m[0]
    widths = np.maximum(0.,np.minimum(y[1:,None],end[None,1:])-np.maximum(y[:-1,None],end[None,:-1]))
    iy, ib = np.where(widths > 1e-15)
    u = wall_conductance(plate, q, x_m, reverse, solid_k, roof_half_m,
                         viscosity=viscosity,rho=rho,cp=cp,liquid_k=liquid_k)
    conduct = widths[iy,ib,None] * np.diff(x_m) * u[ib]
    fluid_ids = np.arange(n*nx).reshape(n,nx)
    exchange = sparse.coo_matrix((conduct.ravel(), (wall_ids[iy].ravel(),fluid_ids[ib].ravel())),
                                 shape=(len(load),n*nx)).tocsr()
    rate = rho*cp*q
    stream = fluid_ids[:,::-1] if reverse else fluid_ids
    advection = sparse.coo_matrix((np.repeat(-rate,nx-1),(stream[:,1:].ravel(),stream[:,:-1].ravel())),
                                  shape=(n*nx,n*nx))
    matrix = sparse.bmat([[solid+sparse.diags(np.asarray(exchange.sum(axis=1)).ravel()),-exchange],
                          [-exchange.T,advection+sparse.diags(np.repeat(rate,nx)
                                             +np.asarray(exchange.sum(axis=0)).ravel())]],format='csc')
    rhs = np.r_[load,np.zeros(n*nx)]
    rise = spsolve(matrix,rhs,permc_spec='MMD_AT_PLUS_A')
    outlet = rise[len(load)+stream[:,-1]]
    residual = np.max(abs(matrix@rise-rhs))
    error = float(rate@outlet-load.sum())
    if not np.isfinite(rise).all() or abs(error)>1e-6*max(1.,load.sum()) or residual>1e-6:
        raise ArithmeticError('conjugate field failed local or global conservation')
    return rise[:len(load)], dict(outlet_rise_k=float(rate@outlet/rate.sum()),max_bulk_rise_k=float(rise[len(load):].max()),
                                  branch_outlet_rise_k=outlet.tolist(), energy_error_w=error,
                                  residual_w=float(residual), solid_nodes=len(load),fluid_nodes=n*nx)
