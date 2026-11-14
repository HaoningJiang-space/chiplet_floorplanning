"""Topology linear programs: exact length versus linearised hot-pair separation.

With rotations fixed and, for every chiplet pair, one fixed side relation
(left/right/below/above with the declared gap), the legal set is a convex
polytope and the two-pin length L = sum |dx| + |dy| is an LP.

Nets between the same two dies depend only on their centre difference D, so
per pair and axis sum_k |D + c_k| is one convex piecewise-linear function of D:
it equals the maximum of its pieces' lines (slope 2*left - K between sorted
breakpoints -c_k). The LP therefore needs one epigraph variable per pair and
axis, and only pieces that intersect the carrier's range of D. This is exact
(same optimum as one variable per net) and about 50x faster on ATPlace cases.
Internal nets (both pins on one die) are constant and omitted.

Thermal proxy (a candidate generator, not a temperature model): coupling between
dies is taken as C = sum P_i P_j / r_ij with Euclidean centre distance r. Its
first-order change at the parent is dC = -sum (P_i P_j / r_ij^2) (d_ij / r_ij) . d(d_ij),
so the LP uses the linear separation score S = sum w_ij u_ij . (c_j - c_i) with
w_ij = P_i P_j / r_ij^2 and unit vector u_ij = d_ij / r_ij at the parent. It is
only valid near the parent: it neither bounds r nor captures that moving dies
also changes the conduction matrix. The LPs trace min L subject to S >= D
between the topology's two extremes; every result needs an exact FV solve.
Units inside the LP: millimetres. LP vertices are snapped to a 1 um corner grid:
unsnapped, HiGHS tolerances leave edges ~1 nm apart, i.e. sliver mesh cells
whose conductances span ~1e18 and fail the solve's residual check.
"""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from .geometry import boxes, is_legal, rotate
from .problem import Layout
from .search import snap

GRID_UM = 1.0  # rounding is monotone, so integer-um sizes, gap and carrier keep every fit legal


def topology(problem, layout, gap_um):
    """Per pair (i, j, axis, sign): the satisfied side relation with the largest slack."""
    b = boxes(problem, layout)/1000
    gap = gap_um/1000
    relations = []
    for i in range(problem.count):
        for j in range(i + 1, problem.count):
            options = [(b[j, 0] - b[i, 2] - gap, 0, 1), (b[i, 0] - b[j, 2] - gap, 0, -1),
                       (b[j, 1] - b[i, 3] - gap, 1, 1), (b[i, 1] - b[j, 3] - gap, 1, -1)]
            slack, axis, sign = max(options)
            if slack < -1e-9:
                raise ValueError("layout is not legal for the declared gap")
            relations.append((i, j, axis, sign))
    return relations


def hot_pairs(problem, layout, count):
    """Largest weights P_i P_j / r^2 (r in mm) with the unit direction d / r at the parent."""
    c = layout.centre_um/1000
    pairs = []
    for i in range(problem.count):
        for j in range(i + 1, problem.count):
            d = c[j] - c[i]
            r = float(np.hypot(*d))
            if r < 1e-9:  # coincident centres cannot occur for legal layouts; keep a defined axis
                d, r = np.array([1.0, 0.0]), 1.0
            pairs.append((problem.power_w[i]*problem.power_w[j]/r**2, i, j, d/r))
    pairs.sort(key=lambda p: -p[0])
    return pairs[:count]


class TopologyLP:
    def __init__(self, problem, layout, gap_um, pairs=10):
        self.problem, self.rotation, self.gap = problem, layout.rotation_deg.copy(), gap_um/1000
        n = problem.count
        size = np.where((self.rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
        width, height = (s/1000 for s in problem.carrier_um)
        centre_bounds = ([(size[k, 0]/2, width - size[k, 0]/2) for k in range(n)]
                         + [(size[k, 1]/2, height - size[k, 1]/2) for k in range(n)])
        offset = rotate(problem.pin_offset_um, self.rotation[problem.pin_chip])/1000  # (m, 2, 2)
        a, b = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
        # Variables: x (n), y (n), then one epigraph t per (axis, die pair with nets).
        rows, cols, vals, rhs = [], [], [], []
        t = 2*n
        for axis in (0, 1):
            const = offset[:, 0, axis] - offset[:, 1, axis]
            for i in range(n):
                for j in range(i + 1, n):
                    c = np.r_[const[(a == i) & (b == j)], -const[(a == j) & (b == i)]]  # |v_i - v_j + c|
                    if not c.size:
                        continue
                    breaks, count = np.unique(-c, return_counts=True)
                    left = np.r_[0, np.cumsum(count)]
                    c_left = np.r_[0, np.cumsum(-breaks*count)]
                    slope, intercept = 2*left - left[-1], 2*c_left - c_left[-1]
                    low = centre_bounds[axis*n + i][0] - centre_bounds[axis*n + j][1]
                    high = centre_bounds[axis*n + i][1] - centre_bounds[axis*n + j][0]
                    keep = (np.r_[breaks, np.inf] >= low - 1e-9) & (np.r_[-np.inf, breaks] <= high + 1e-9)
                    k = int(keep.sum())
                    # slope (v_i - v_j) + intercept - t <= 0
                    idx = len(rhs) + np.arange(k)
                    rows += [idx, idx, idx]
                    cols += [np.full(k, axis*n + i), np.full(k, axis*n + j), np.full(k, t)]
                    vals += [slope[keep], -slope[keep], -np.ones(k)]
                    rhs += list(-intercept[keep])
                    t += 1
        r = len(rhs)
        rhs = [np.array(rhs)]
        for i, j, axis, sign in topology(problem, layout, gap_um):
            first, second = (i, j) if sign > 0 else (j, i)
            # v_first + size_first/2 + gap <= v_second - size_second/2
            rows += [np.array([r]), np.array([r])]
            cols += [np.array([axis*n + first]), np.array([axis*n + second])]
            vals += [np.array([1.0]), np.array([-1.0])]
            rhs.append(np.array([-(size[first, axis] + size[second, axis])/2 - self.gap]))
            r += 1
        self.nvar = t
        self.A = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                   shape=(r, self.nvar))
        self.b = np.concatenate(rhs)
        self.bounds = centre_bounds + [(0, None)]*(t - 2*n)
        self.length = np.r_[np.zeros(2*n), np.ones(t - 2*n)]  # mm of inter-die pin length
        self.heat = np.zeros(self.nvar)
        for weight, i, j, direction in hot_pairs(problem, layout, pairs):
            for axis in (0, 1):
                self.heat[axis*n + j] += weight*direction[axis]
                self.heat[axis*n + i] -= weight*direction[axis]

    def _solve(self, objective, extra=None):
        A, b = self.A, self.b
        if extra is not None:
            A, b = sparse.vstack([A, extra[0][None]]), np.r_[b, extra[1]]
        result = linprog(objective, A_ub=A, b_ub=b, bounds=self.bounds, method="highs")
        return result.x if result.status == 0 else None

    def _layout(self, x):
        n = self.problem.count
        centre = snap(self.problem, np.stack((x[:n], x[n:2*n]), axis=1)*1000, self.rotation, GRID_UM)
        layout = Layout(centre, self.rotation.copy())
        return layout if is_legal(self.problem, layout, self.gap*1000) else None

    def sweep(self, levels):
        """Legal, grid-snapped layouts minimising L at `levels` separation targets
        between the two LP extremes; snapped layouts failing the exact legality
        check are dropped. min L is usually degenerate, so the sweep starts at the
        shortest layout with the largest separation (lexicographic), which makes
        the targets independent of which optimal vertex the solver returns."""
        shortest = self._solve(self.length)
        if shortest is None:
            return []
        shortest = self._solve(-self.heat, (self.length, self.length @ shortest + 1e-6))
        widest = self._solve(-self.heat + 1e-6*self.length)
        if shortest is None or widest is None:
            return []
        low, high = self.heat @ shortest, self.heat @ widest
        out = [shortest]
        for target in np.linspace(low, high, levels)[1:]:
            x = self._solve(self.length, (-self.heat, -target))
            if x is not None:
                out.append(x)
        layouts = [self._layout(x) for x in out]
        return [layout for layout in layouts if layout is not None]
