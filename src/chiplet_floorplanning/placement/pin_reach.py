"""Joint translations with exact oriented-pin reach inside one non-overlap cell."""

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from .geometry import is_legal, pin_manhattan_um, pin_points_um, rotate
from .lp import TopologyLP, topology
from .search import layout_key
from .thermal import peak_sensitivity


def reach_rows(problem, rotation, limits_mm, nvar):
    """Four inequalities per linked die pair suffice for all its individual pins."""
    n = problem.count
    limits = np.asarray(limits_mm, dtype=float)
    if limits.shape != (len(problem.pin_chip),) or not np.all(np.isfinite(limits) & (limits > 0)):
        raise ValueError('one positive reach in mm is required for each signal')
    a, b = problem.pin_chip.T
    offset = rotate(problem.pin_offset_um, rotation[problem.pin_chip])/1000
    diff = (offset[:,0]-offset[:,1])*np.where(a<=b,1.,-1.)[:,None]
    pairs, group = np.unique(np.sort(problem.pin_chip,axis=1),axis=0,return_inverse=True)
    rows, rhs = [], []
    for sx, sy in ((1,1),(-1,-1),(1,-1),(-1,1)):
        tight = np.full(len(pairs),np.inf)
        np.minimum.at(tight,group,limits-diff@np.array([sx,sy]))
        for (i,j), bound in zip(pairs,tight):
            row = np.zeros(nvar)
            row[i] += sx
            row[j] -= sx
            row[n+i] += sy
            row[n+j] -= sy
            rows.append(row)
            rhs.append(bound)
    return sparse.csr_matrix(np.array(rows).reshape(-1,nvar)), np.asarray(rhs)


def required_travel_mm(problem, start, reach_mm, displacement_mm, gap_um=100):
    """Lower bound each follower's maximum-axis travel for each specified leader move.

    Entry (i,j) treats the requested displacement of i as fixed; all other displacements
    are unknown. Pin-only bounds apply throughout the fixed-orientation space. The
    second array additionally uses the rectangular separation relations of this cell.
    """
    xy = np.asarray(start.centre_um) / 1000
    delta = np.asarray(displacement_mm)
    reach = np.asarray(reach_mm)
    a, b = problem.pin_chip.T
    pins = pin_points_um(problem, start) / 1000
    offset = pins[:, 0] - pins[:, 1]
    if delta.shape != xy.shape or reach.shape != a.shape:
        raise ValueError('supply one displacement per chiplet and one reach per signal')
    n = problem.count
    pin_bound = np.zeros((n, n))
    def propagate(direction, edges, slack, bound):
        # An edge i -> j implies s.d_j >= s.d_i - slack_ij.
        if np.any(slack < -1e-8):
            raise ValueError('the starting pose violates a propagation constraint')
        distance = np.full((n, n), np.inf)
        np.minimum.at(distance, edges, np.maximum(0., slack))
        np.fill_diagonal(distance, 0.)
        for k in range(n):
            np.minimum(distance, distance[:, k, None] + distance[None, k, :], out=distance)
        travel = ((delta @ direction)[:, None] - distance) / np.abs(direction).sum()
        np.maximum(bound, travel, out=bound)

    for direction in np.array([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        diff = offset @ direction
        propagate(direction, (np.r_[a,b], np.r_[b,a]), np.r_[reach-diff, reach+diff], pin_bound)
    cell_bound = pin_bound.copy()
    size = np.where((start.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um) / 1000
    side_order = topology(problem, start, gap_um)
    for axis in (0, 1):
        pairs = [(i,j) if sign > 0 else (j,i) for i,j,ax,sign in side_order if ax == axis]
        if not pairs:
            continue
        low, high = np.array(pairs).T
        slack = xy[high,axis]-xy[low,axis]-(size[low,axis]+size[high,axis])/2-gap_um/1000
        direction = np.eye(2)[axis]
        propagate(direction, (low, high), slack, cell_bound)
        propagate(-direction, (high, low), slack, cell_bound)
    np.fill_diagonal(pin_bound, 0.)
    np.fill_diagonal(cell_bound, 0.)
    return pin_bound, cell_bound


class PinReachCell(TopologyLP):
    """A bounded continuous geometry cell, with fixed rotations and pair order."""

    def __init__(self, problem, layout, gap_um, limits_mm, cap_m):
        super().__init__(problem,layout,gap_um)
        rows, rhs = reach_rows(problem,self.rotation,limits_mm,self.nvar)
        self.A = sparse.vstack((self.A, rows, self.length[None]),format='csr')
        self.b = np.r_[self.b,rhs,cap_m*1000-self.internal_mm]
        self.pin_rows = len(rhs)
        self.limits_mm, self.cap_m = limits_mm, cap_m

    def cool_direction(self, start, peaks, gradients, radius_mm):
        """Minimise worst linearised temperature, then minimise total movement at that value."""
        n = self.problem.count
        xy = start.centre_um.T.ravel()/1000
        g = np.concatenate((gradients[:,:,0],gradients[:,:,1]),axis=1)
        hot = sparse.hstack((sparse.csr_matrix(g),sparse.csr_matrix((len(peaks),self.nvar-2*n))))
        matrix = sparse.bmat([[self.A,None],[hot,-np.ones((len(peaks),1))]],format='csr')
        rhs = np.r_[self.b,g@xy-peaks]
        bounds = self.bounds.copy()
        for j,t in enumerate(xy):
            lo,hi=bounds[j]
            bounds[j]=(max(lo,t-radius_mm),min(hi,t+radius_mm))
        first=linprog(np.r_[np.zeros(self.nvar),1.],A_ub=matrix,b_ub=rhs,
                      bounds=bounds+[(None,None)],method='highs')
        if not first.success:
            raise ValueError(first.message)
        ident=sparse.eye(2*n,self.nvar,format='csr')
        small=sparse.eye(2*n,format='csr')
        matrix=sparse.bmat([[self.A,None],[hot,None],[ident,-small],[-ident,-small]],format='csr')
        rhs=np.r_[self.b,g@xy-peaks+first.fun+1e-6,xy,-xy]
        second=linprog(np.r_[np.zeros(self.nvar),np.ones(2*n)],A_ub=matrix,b_ub=rhs,
                       bounds=bounds+[(0,None)]*(2*n),method='highs')
        if not second.success:
            raise ValueError(second.message)
        return (second.x[:2*n]-xy).reshape(2,n).T, float(first.fun)

    def toward(self, xy_um):
        """Closest joint layout in maximum coordinate displacement to a target."""
        k = 2*self.problem.count
        ident = sparse.eye(k,self.nvar,format='csr')
        mat = sparse.vstack((self.A,ident,-ident))
        slack = np.r_[np.zeros(len(self.b)),-np.ones(2*k)]
        mat = sparse.hstack((mat,slack[:,None]),format='csr')
        xy = np.asarray(xy_um).T.ravel()/1000
        obj = np.r_[1e-8*self.length,1.]
        rhs = self.b.copy()
        for attempt in range(2):
            result = linprog(obj,A_ub=mat,b_ub=np.r_[rhs,xy,-xy],
                             bounds=self.bounds+[(0,None)],method='highs')
            if not result.success:
                return None
            layout = self._layout(result.x)
            if layout is not None:
                lengths = pin_manhattan_um(self.problem,layout)/1000
                if np.all(lengths <= self.limits_mm+1e-9) and lengths.sum() <= self.cap_m*1000+1e-6:
                    return layout
            # Rounding four endpoint coordinates to 1 µm costs at most 2 µm per net.
            if attempt == 0:
                rhs[-self.pin_rows-1:-1] -= .002001
                rhs[-1] -= .002001*len(self.limits_mm)
        return None


def half_space_gradients(problem, start, hot):
    """Derivative of off-die surface point heating on a homogeneous copper half-space, K/mm."""
    xy = start.centre_um / 1000
    offsets = xy[hot, None, :] - xy[None, :, :]
    distance = np.linalg.norm(offsets, axis=2)
    rows = np.arange(len(hot))
    distance[rows, hot] = np.inf
    scale = 1000 / (2 * np.pi * 400.)  # use mm distances with conductivity in W/(m K)
    gradients = offsets * (scale * problem.power_w[None, :] / distance**3)[:, :, None]
    gradients[rows, hot] = -gradients.sum(axis=1)
    return gradients


def heat_directed_moves(problem, start, reach_mm, total_m, gap_um=100, resolution=64, gradient_model='package'):
    """Propose full/half joint translations from five hotspot responses at any admissible start.

    Pin limits follow the source net order. This objective uses absolute temperatures in °C,
    including when the input also carries limits for a separate temperature-margin study.
    'package' uses hotspot adjoints. 'copper-half-space' uses a point-source slope with the
    same measured starting temperatures. Verify returned layouts with the 3D evaluator.
    """
    reach = np.asarray(reach_mm, dtype=float)
    if not is_legal(problem, start, gap_um):
        raise ValueError('starting layout violates the carrier boundary or minimum spacing')
    lengths = pin_manhattan_um(problem, start)/1000
    if (reach.shape != lengths.shape or np.any(lengths > reach+1e-9)
            or not np.isfinite(total_m) or lengths.sum()/1000 > total_m+1e-9):
        raise ValueError('starting layout violates the supplied pin or total-length budget')
    cell = PinReachCell(problem, start, gap_um, reach, total_m)
    peaks, gradient = peak_sensitivity(problem, start, gap_um, resolution)
    if problem.limit_c is not None:
        peaks = peaks + problem.limit_c
    hot = np.argsort(-peaks, kind='stable')[:5].tolist()
    if gradient_model == 'package':
        grad = gradient(hot)[hot]
    elif gradient_model == 'copper-half-space':
        grad = half_space_gradients(problem, start, hot)
    else:
        raise ValueError('unknown hotspot gradient model')
    radius = float(np.median(problem.size_um.min(axis=1))/2000)
    delta, prediction = cell.cool_direction(start, peaks[hot], grad, radius)
    seen = {layout_key(start)}
    moves = []
    for fraction in (1., .5):
        pose = cell.toward(start.centre_um+1000*delta*fraction)
        if pose is None or layout_key(pose) in seen:
            continue
        seen.add(layout_key(pose))
        actual_delta = (pose.centre_um-start.centre_um)/1000
        forecast = (peaks[hot]+np.einsum('ijk,jk->i',grad,actual_delta)).max()
        moves.append((fraction, pose, float(forecast)))
    return dict(start_peak_c=float(peaks.max()),hot_dies=[problem.names[i] for i in hot],
                hot_peaks_c=peaks[hot].tolist(),radius_mm=radius,predicted_full_c=prediction), moves
