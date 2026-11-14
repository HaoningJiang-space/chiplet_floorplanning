"""Topology linear programs: exact length versus linearised hot-pair separation.

With rotations fixed and, for every chiplet pair, one fixed side relation
(left/right/below/above with the declared gap), the legal set is a convex
polytope and the two-pin length L = sum |dx| + |dy| is an LP.

Thermal proxy (a candidate generator, not a temperature model): coupling between
dies is taken as C = sum P_i P_j / r_ij with Euclidean centre distance r. Its
first-order change at the parent is dC = -sum (P_i P_j / r_ij^2) (d_ij / r_ij) . d(d_ij),
so the LP uses the linear separation score S = sum w_ij u_ij . (c_j - c_i) with
w_ij = P_i P_j / r_ij^2 and unit vector u_ij = d_ij / r_ij at the parent. It is
only valid near the parent: it neither bounds r nor captures that moving dies
also changes the conduction matrix. The LPs trace min L subject to S >= D
between the topology's two extremes; every result needs an exact FV solve.
Units inside the LP: millimetres.
"""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from .geometry import boxes, is_legal, rotate
from .problem import Layout

SLACK_MM = 1e-6  # first attempt keeps HiGHS tolerances on the legal side of every gap


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
        n, m = problem.count, len(problem.pin_chip)
        size = np.where((self.rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
        offset = rotate(problem.pin_offset_um, self.rotation[problem.pin_chip])/1000  # (m, 2, 2)
        # Variables: x (n), y (n), tx (m), ty (m); tx >= |x_a - x_b + c|.
        self.nvar = 2*n + 2*m
        rows, cols, vals, rhs = [], [], [], []
        r = 0
        a, b = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
        for axis in (0, 1):
            const = offset[:, 0, axis] - offset[:, 1, axis]
            t = 2*n + axis*m + np.arange(m)
            for s in (1, -1):
                # s (v_a - v_b + c) - t <= 0
                idx = r + np.arange(m)
                rows += [idx, idx, idx]
                cols += [axis*n + a, axis*n + b, t]
                vals += [np.full(m, s), np.full(m, -s), np.full(m, -1.0)]
                rhs.append(-s*const)
                r += m
        # Internal nets (a == b) cancel exactly: their rows reduce to |c| <= t.
        self.pair_rows = []
        for i, j, axis, sign in topology(problem, layout, gap_um):
            first, second = (i, j) if sign > 0 else (j, i)
            # v_first + size_first/2 + gap <= v_second - size_second/2
            rows += [np.array([r]), np.array([r])]
            cols += [np.array([axis*n + first]), np.array([axis*n + second])]
            vals += [np.array([1.0]), np.array([-1.0])]
            rhs.append(np.array([-(size[first, axis] + size[second, axis])/2 - self.gap]))
            self.pair_rows.append(r)
            r += 1
        self.A = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                   shape=(r, self.nvar))
        self.exact_b = np.concatenate(rhs)
        self.b = self.exact_b
        width, height = (s/1000 for s in problem.carrier_um)
        self.bounds = ([(size[k, 0]/2, width - size[k, 0]/2) for k in range(n)]
                       + [(size[k, 1]/2, height - size[k, 1]/2) for k in range(n)] + [(0, None)]*(2*m))
        self.length = np.r_[np.zeros(2*n), np.ones(2*m)]  # mm of pin length
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
        centre = np.round(np.stack((x[:n], x[n:2*n]), axis=1)*1000, 3)
        layout = Layout(centre, self.rotation.copy())
        return layout if is_legal(self.problem, layout, self.gap*1000) else None

    def sweep(self, levels):
        """Layouts minimising L at `levels` separation targets between the two LP extremes.

        Tries a 1 nm safety margin on every pair gap first; layouts that only fit
        exactly (e.g. dies filling the carrier) are retried without it. Only
        layouts passing the exact legality check are returned.
        """
        for slack in (SLACK_MM, 0.0):
            self.b = self.exact_b.copy()
            self.b[self.pair_rows] -= slack
            layouts = self._sweep(levels)
            if layouts:
                return layouts
        return []

    def _sweep(self, levels):
        shortest = self._solve(self.length)
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
