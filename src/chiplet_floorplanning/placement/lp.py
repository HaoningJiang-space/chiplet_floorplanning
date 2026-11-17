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
from .thermal import AMBIENT_C

GRID_UM = 1.0  # rounding is monotone, so integer-um sizes, gap and carrier keep every fit legal
REACH_MARGIN_MM = 0.005


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


def centre_relations(problem, layout, gap_um):
    """Per pair (i, j, axis, sign) read from the centres even if the boxes overlap: the axis on which the centres
    are farther apart relative to the pair's half-sizes, and its order. The LP then enforces the separation, so
    a relation set from any arrangement (e.g. after a rotation that makes two dies overlap) is a legalisation."""
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    c = layout.centre_um
    relations = []
    for i in range(problem.count):
        for j in range(i + 1, problem.count):
            d = c[j] - c[i]
            reach = (size[i] + size[j])/2 + gap_um
            axis = int(np.argmax(np.abs(d)/reach))
            relations.append((i, j, axis, 1 if d[axis] >= 0 else -1))
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
    def __init__(self, problem, layout, gap_um, pairs=10, relations=None):
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
        for i, j, axis, sign in relations if relations is not None else topology(problem, layout, gap_um):
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


class ReachLP:
    """Topology LP for link reach: with the parent's rotations and side relations fixed, the rectangle gap of
    every linked die pair is exact in the LP (separation along the relation axis plus the excess of the centre
    offset over the half-sizes across it), so min total over-reach is an LP; zero means every link fits.
    `sweep` then trades the same linearised hot-pair separation as TopologyLP while keeping over-reach zero."""

    def __init__(self, problem, layout, gap_um, links, reach_mm, pairs=10):
        self.problem, self.rotation, self.gap = problem, layout.rotation_deg.copy(), gap_um/1000
        n = problem.count
        size = np.where((self.rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
        width, height = (s/1000 for s in problem.carrier_um)
        bounds = ([(size[k, 0]/2, width - size[k, 0]/2) for k in range(n)]
                  + [(size[k, 1]/2, height - size[k, 1]/2) for k in range(n)])
        relation = {}
        rows, cols, vals, rhs = [], [], [], []

        def row(entries, value):
            r = len(rhs)
            for c, v in entries:
                rows.append(r)
                cols.append(c)
                vals.append(v)
            rhs.append(value)

        for i, j, axis, sign in topology(problem, layout, gap_um):
            first, second = (i, j) if sign > 0 else (j, i)
            relation[(i, j)] = (first, second, axis)
            row([(axis*n + first, 1.0), (axis*n + second, -1.0)], -(size[first, axis] + size[second, axis])/2 - self.gap)
        nvar = 2*n
        self.excess = []
        for i, j in links:
            i, j = (int(i), int(j)) if i < j else (int(j), int(i))
            first, second, axis = relation[(i, j)]
            across = 1 - axis
            p, e = nvar, nvar + 1
            nvar += 2
            half = (size[i, across] + size[j, across])/2
            row([(across*n + i, 1.0), (across*n + j, -1.0), (p, -1.0)], half)    # p >= (u_i - u_j) - half
            row([(across*n + j, 1.0), (across*n + i, -1.0), (p, -1.0)], half)    # p >= (u_j - u_i) - half
            sep = (size[first, axis] + size[second, axis])/2
            # e >= (v_second - v_first - sep) + p - reach
            # REACH_MARGIN_MM keeps the 1 um snap of _layout from pushing a fitted link past the reach
            row([(axis*n + second, 1.0), (axis*n + first, -1.0), (p, 1.0), (e, -1.0)], sep + reach_mm - REACH_MARGIN_MM)
            self.excess.append(e)
        self.nvar = nvar
        self.A = sparse.csr_matrix((vals, (rows, cols)), shape=(len(rhs), nvar))
        self.b = np.array(rhs)
        self.bounds = bounds + [(0, None)]*(nvar - 2*n)
        self.over = np.zeros(nvar)
        self.over[self.excess] = 1.0
        self.heat = np.zeros(nvar)
        for weight, i, j, direction in hot_pairs(problem, layout, pairs):
            for axis in (0, 1):
                self.heat[axis*n + j] += weight*direction[axis]
                self.heat[axis*n + i] -= weight*direction[axis]

    _layout = TopologyLP._layout

    def _solve(self, objective, *extra):
        A, b = self.A, self.b
        if extra:
            A = sparse.vstack([A] + [sparse.csr_matrix(r[None]) for r, _ in extra])
            b = np.r_[b, [v for _, v in extra]]
        result = linprog(objective, A_ub=A, b_ub=b, bounds=self.bounds, method="highs")
        return result.x if result.status == 0 else None

    def fit(self):
        """(min total over-reach in mm, its snapped legal layout or None); (inf, None) if the LP fails."""
        x = self._solve(self.over)
        if x is None:
            return np.inf, None
        return float(self.over @ x), self._layout(x)

    def sweep(self, levels):
        """Legal snapped layouts with zero over-reach at `levels` separation targets from the least to the most
        separated; empty if this topology cannot fit every link."""
        fit = self._solve(self.over)
        if fit is None or self.over @ fit > 1e-6:
            return []
        within = (self.over, 1e-6)
        low, high = self._solve(self.heat, within), self._solve(-self.heat, within)
        if low is None or high is None:
            return []
        out = [low]
        for target in np.linspace(self.heat @ low, self.heat @ high, levels)[1:]:
            x = self._solve(self.over, (-self.heat, -target))
            if x is not None and self.over @ x <= 1e-6:
                out.append(x)
        layouts = [self._layout(x) for x in out]
        return [layout for layout in layouts if layout is not None]


SLP_RADIUS_MM = (2.0, 0.05, 10.0)  # initial, smallest and largest trust-region half-width
SLP_BAND_K = 20.0                  # dies within this distance of the cap get a linearised peak constraint


def slp_chain(args):
    """Trust-region sequential LP from one layout, within its topology, in one of two modes.

    args = (problem, layout, gap_um, resolution, target, steps[, mode]):
    - mode 'peak' (default), target = die-peak cap (degC): min exact length with every near-cap die's peak
      linearised by `die_peak_sensitivity` kept under the cap; from a layout above the cap, min the
      linearised hottest die first.
    - mode 'length', target = length budget (m): min the linearised hottest die with the exact length LP kept
      within the budget; from a layout over the budget, min length without heating its hottest die.
    Steps stay inside a box trust region; a step is kept only if the exact solve of the snapped candidate
    confirms it, the radius then grows, otherwise it halves. One LU factorisation per step serves both the
    exact check and the next gradients; adjoints are solved only for the near-peak dies the LP linearises at
    the current layout, once per layout (none for a rejected candidate or with steps=0). Returns every exactly
    solved (layout, die peaks degC) pair.
    """
    from .geometry import pin_manhattan_um
    from .thermal import peak_sensitivity
    problem, layout, gap_um, resolution, target, steps = args[:6]
    mode = args[6] if len(args) > 6 else "peak"
    n = problem.count
    inside = problem.pin_chip[:, 0] == problem.pin_chip[:, 1]
    radius, smallest, largest = SLP_RADIUS_MM
    peaks, gradient = peak_sensitivity(problem, layout, gap_um, resolution)
    known = {}                                    # die -> gradient row at the current layout

    def grad_rows(dies):
        missing = [i for i in dies if i not in known]
        if missing:
            g = gradient(missing)
            known.update((i, g[i]) for i in missing)
        return np.array([known[i] for i in dies]).reshape(len(dies), n, 2)

    solved = [(layout, peaks)]
    current, length = layout, pin_manhattan_um(problem, layout).sum()/1000
    for _ in range(steps):
        lp = TopologyLP(problem, current, gap_um, pairs=0)
        x0 = current.centre_um.T.ravel()/1000
        hottest = peaks.max()
        if mode == "peak":
            hot = np.flatnonzero(peaks >= target - SLP_BAND_K)
            minimise_peak = hottest > target          # above the cap: cool first
        else:
            hot = np.flatnonzero(peaks >= hottest - SLP_BAND_K)
            budget = target*1000 - pin_manhattan_um(problem, current)[inside].sum()/1000   # LP covers inter-die nets
            minimise_peak = length <= target*1000     # within budget: cool; over it: shorten without heating
        grad = grad_rows(hot.tolist())
        g = np.zeros((hot.size, lp.nvar))
        g[:, :2*n] = np.concatenate([grad[:, :, 0], grad[:, :, 1]], axis=1)
        rows, rhs, objective, extra = [lp.A], [lp.b], lp.length, []
        if minimise_peak:   # epigraph t >= linearised peak of every hot die
            rows = [sparse.hstack([lp.A, sparse.csr_matrix((lp.A.shape[0], 1))]),
                    sparse.hstack([sparse.csr_matrix(g), -np.ones((hot.size, 1))])]
            rhs = [lp.b, g[:, :2*n] @ x0 - peaks[hot]]
            objective, extra = np.r_[1e-6*lp.length, 1.0], [(None, None)]
            if mode == "length":
                rows.append(sparse.csr_matrix(np.r_[lp.length, 0.0][None]))
                rhs.append([budget])
        else:
            limit = target if mode == "peak" else hottest
            rows.append(sparse.csr_matrix(g))
            rhs.append(limit - peaks[hot] + g[:, :2*n] @ x0)
        bounds = [(max(lo, x0[k] - radius), min(hi, x0[k] + radius)) if k < 2*n else (lo, hi)
                  for k, (lo, hi) in enumerate(lp.bounds)] + extra
        result = linprog(objective, A_ub=sparse.vstack(rows), b_ub=np.concatenate(rhs), bounds=bounds,
                         method="highs")
        candidate = lp._layout(result.x[:lp.nvar]) if result.status == 0 else None
        if candidate is None or np.array_equal(candidate.centre_um, current.centre_um):
            radius /= 2
        else:
            new_peaks, new_gradient = peak_sensitivity(problem, candidate, gap_um, resolution)
            solved.append((candidate, new_peaks))
            new_length = pin_manhattan_um(problem, candidate).sum()/1000
            if mode == "peak":
                keep = (new_peaks.max() < hottest - 1e-9 if minimise_peak
                        else new_peaks.max() <= target and new_length < length - 1e-9)
            else:
                keep = (new_peaks.max() < hottest - 1e-9 and new_length <= target*1000 + 1e-9 if minimise_peak
                        else new_length < length - 1e-9 and new_peaks.max() <= hottest + 1e-9)
            if keep:
                current, peaks, gradient, length = candidate, new_peaks, new_gradient, new_length
                known.clear()
                radius = min(1.5*radius, largest)
            else:
                radius /= 2
        if radius < smallest:
            break
    return solved


def _free_move(problem, layout, rng):
    """One unconstrained move (overlap allowed): the relation LP legalises it."""
    centre, rotation = layout.centre_um.copy(), layout.rotation_deg.copy()
    k = int(rng.integers(problem.count))
    kind = rng.choice(("attach", "rotate", "swap", "relocate", "shift"), p=(.35, .2, .2, .1, .15))
    if kind == "attach":
        # Put k against one side of a partner drawn by shared net count, with a random rotation: the moves
        # that make heavy pairs adjacent with facing pins, which random shifts rarely hit.
        a, b = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
        partners = np.bincount(np.r_[b[a == k], a[b == k]], minlength=problem.count).astype(float)
        if partners.sum() > 0:
            j = int(rng.choice(problem.count, p=partners/partners.sum()))
            rotation[k] = rng.choice((0, 90, 180, 270))
            size = np.where((rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
            axis, sign = int(rng.integers(2)), rng.choice((-1, 1))
            centre[k] = centre[j]
            centre[k, axis] += sign*(size[j, axis] + size[k, axis])/2
            centre[k, 1 - axis] += rng.uniform(-.5, .5)*size[j, 1 - axis]
    elif kind == "rotate":
        rotation[k] = (rotation[k] + rng.choice((90, 180, 270))) % 360
    elif kind == "swap":
        j = int(rng.integers(problem.count - 1))
        j += j >= k
        centre[[k, j]] = centre[[j, k]]
    elif kind == "relocate":
        centre[k] = rng.uniform(0, 1, 2)*np.array(problem.carrier_um)
    else:
        centre[k, rng.integers(2)] += rng.normal(0, 3000)
    return Layout(centre, rotation)


def length_anneal(args):
    """Simulated annealing over relation sets and rotations for the exact two-pin length (no FV).

    Each step moves one die freely, reads every pair's relation from the centres (`centre_relations`) and
    solves the length LP of that relation set, which both legalises and optimises the positions; infeasible
    or illegal results are rejected. Returns (best layout, its length in m)."""
    from .geometry import pin_manhattan_um
    problem, layout, gap_um, seed, steps, t_start, t_end = args
    rng = np.random.default_rng(seed)
    length = lambda l: float(pin_manhattan_um(problem, l).sum())/1e6
    current = best = layout
    now = top = length(layout)
    if t_start <= 0 or top <= 0:   # no inter-die nets: nothing to shorten
        return best, top
    for step in range(steps):
        temperature = t_start*(t_end/t_start)**(step/max(steps - 1, 1))
        moved = _free_move(problem, current, rng)
        lp = TopologyLP(problem, moved, gap_um, pairs=0, relations=centre_relations(problem, moved, gap_um))
        x = lp._solve(lp.length)
        candidate = lp._layout(x) if x is not None else None
        if candidate is None:
            continue
        new = length(candidate)
        if new <= now or rng.random() < np.exp(-(new - now)/temperature):
            current, now = candidate, new
            if new < top:
                best, top = candidate, new
    return best, top


MILP_STATUS = dict(status=None)   # outcome of the last _solve_milp call, for callers that must tell timeout from proof


def _solve_milp(cost, matrix, lo, hi, integrality, bounds, time_limit_s, threads=1, focus=0, start=None):
    """Gurobi when gurobipy and a licence are available (ATPlace2.5D's own solver), else HiGHS. `threads` and
    `focus` (Gurobi MIPFocus; 1 = find feasible solutions first) only apply to Gurobi, as does `start` (a partial
    MIP start: NaN entries are left for the solver to complete)."""
    try:
        import gurobipy as gp
        model = gp.Model()
        model.Params.OutputFlag, model.Params.TimeLimit, model.Params.Threads = 0, time_limit_s, threads
        model.Params.MIPFocus = focus
        v = model.addMVar(len(cost), lb=bounds.lb, ub=bounds.ub,
                          vtype=np.where(integrality > 0, gp.GRB.BINARY, gp.GRB.CONTINUOUS))
        finite_hi, finite_lo = np.isfinite(hi), np.isfinite(lo)
        if finite_hi.any():
            model.addMConstr(matrix[finite_hi], v, '<', hi[finite_hi])
        if finite_lo.any():
            model.addMConstr(matrix[finite_lo], v, '>', lo[finite_lo])
        model.setObjective(cost @ v)
        if start is not None:
            v.Start = np.where(np.isfinite(start), start, gp.GRB.UNDEFINED)
        model.optimize()
        MILP_STATUS['status'] = {gp.GRB.OPTIMAL: 'optimal', gp.GRB.INFEASIBLE: 'infeasible',
                                 gp.GRB.TIME_LIMIT: 'time_limit'}.get(model.Status, str(model.Status))
        return v.X if model.SolCount else None
    except ImportError:
        pass
    except Exception as error:   # no licence: fall back rather than fail
        if 'icense' not in str(error):
            raise
    from scipy.optimize import LinearConstraint, milp
    result = milp(cost, constraints=LinearConstraint(matrix, lo, hi), integrality=integrality, bounds=bounds,
                  options=dict(time_limit=time_limit_s, disp=False))
    MILP_STATUS['status'] = {0: 'optimal', 1: 'time_limit', 2: 'infeasible'}.get(result.status, str(result.status))
    return result.x


def pin_length_cut(problem, layout, ix, iy, iz):
    """Linear minorant of the exact per-pin Manhattan length (mm), tight at `layout`: sum_e,a sigma_ea d_ea with
    sigma = sign(d) at the layout and d_ea = c_i + R_i o_e - c_j - R_j o'_e linear in the centres and the rotation
    one-hots. Returns (MILP row entries, constant mm of nets inside one die, whose length no rotation changes)."""
    from .geometry import pin_points_um, rotate
    a, b = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
    inside = a == b
    points = pin_points_um(problem, layout)
    sigma = np.sign(points[:, 0] - points[:, 1])            # (m, 2)
    turns = np.array([0, 90, 180, 270])
    coef = {}
    for e in np.flatnonzero(~inside):
        for axis, base in ((0, ix), (1, iy)):
            s = sigma[e, axis]
            if s == 0:
                continue
            coef[base + a[e]] = coef.get(base + a[e], 0.0) + s
            coef[base + b[e]] = coef.get(base + b[e], 0.0) - s
            for die, offset, sign in ((a[e], problem.pin_offset_um[e, 0], 1.0), (b[e], problem.pin_offset_um[e, 1], -1.0)):
                turned = rotate(np.tile(offset/1000, (4, 1)), turns)[:, axis]
                for r in range(4):
                    coef[iz + 4*die + r] = coef.get(iz + 4*die + r, 0.0) + sign*s*turned[r]
    constant = float(np.abs(problem.pin_offset_um[inside, 0] - problem.pin_offset_um[inside, 1]).sum())/1000
    return [(k, v) for k, v in coef.items() if v != 0.0], constant


def wire_clusters(problem):
    """(i, j, nets, mean pin offset on i, mean pin offset on j) per connected pair, mm in the die frames."""
    a, b = problem.pin_chip[:, 0], problem.pin_chip[:, 1]
    clusters = []
    for i in range(problem.count):
        for j in range(i + 1, problem.count):
            fwd, bwd = (a == i) & (b == j), (a == j) & (b == i)
            k = int(fwd.sum() + bwd.sum())
            if k:
                oi = np.r_[problem.pin_offset_um[fwd, 0], problem.pin_offset_um[bwd, 1]].mean(axis=0)/1000
                oj = np.r_[problem.pin_offset_um[fwd, 1], problem.pin_offset_um[bwd, 0]].mean(axis=0)/1000
                clusters.append((i, j, k, oi, oj))
    return clusters


def cluster_length_mm(problem, layout):
    """The MILP's clustered wirelength (sum K_ij |c_i + R o_i - c_j - R o_j|_1, mm) at a fixed layout; a lower bound
    of the exact pin length, used so that wire budgets and the MILP row measure the same quantity."""
    from .geometry import rotate
    total = 0.0
    for i, j, k, oi, oj in wire_clusters(problem):
        pi = layout.centre_um[i]/1000 + rotate(oi[None], layout.rotation_deg[i:i + 1])[0]
        pj = layout.centre_um[j]/1000 + rotate(oj[None], layout.rotation_deg[j:j + 1])[0]
        total += k*float(np.abs(pi - pj).sum())
    return total


def milp_relations(problem, gap_um, time_limit_s=60.0, thermal=None, proxy=None, wire_mm=None,
                   threads=1, focus=0, wire_cuts=(), directions=None, start=None):
    """Global choice of rotations and side relations for wirelength by MILP (HiGHS), after ATPlace2.5D's
    initialisation: each die has one-hot quarter-turn binaries; each pair has four big-M side binaries; the
    pair's nets are clustered at their mean pin offsets, so the objective is sum K_ij |c_i + R o_i - c_j - R o_j|
    (a lower bound of the exact length by convexity). Returns a Layout whose centres realise the chosen
    relations (overlap-free up to the solver tolerance), to be finished by the exact relation LP, or None.
    `thermal` = (ThermalTable, cap degC or None) adds the grid-kernel temperature rows of thermal_milp: a hard cap on
    the kernel peak, or with None the kernel peak itself is minimised (wirelength only breaks ties).
    `wire_mm` (or a third proxy entry) bounds the clustered wirelength (cluster_length_mm units), with or without
    the proxy. With `directions` = K the proxy's pair distance is the
    K-direction polygonal lower bound of the centre distance (rho <= u_k . (c_j - c_i) for one chosen k; within
    cos(pi/K) of it) instead of the separation along the side relation (docs/polygon-distance-plan.md). `start`
    (a layout inside the carrier) is a partial MIP start: its centres, rotations, side relations and, with
    directions, the best direction of every pair; the solver completes the rest. Since that is only a relaxation of the exact per-pin length,
    `wire_cuts` (layouts that broke the exact budget) add pin_length_cut rows: valid for every layout, tight at the
    cut layout, so each excludes it (docs/proxy-budget-review.md section 3); they need `wire_mm`.
    `proxy` = (ThermalProxy, cap or None[, wire budget mm]) adds the axial tangent envelope: rho <= separation along the chosen side
    relation, tau >= tangents of g(rho), and t >= P_i s_i + sum_j P_j tau_ij - limit_i for every observer (including
    unpowered dies). Omit limit_i when no limits are given. The cap is in degC, or overshoot K with Problem.limit_c;
    with None the envelope is minimised (wire length breaks ties). A wire budget bounds the clustered wirelength
    (cluster_length_mm). This envelope is not an FV upper bound."""
    from scipy.optimize import Bounds
    from .geometry import rotate
    n = problem.count
    width, height = (s/1000 for s in problem.carrier_um)
    gap = gap_um/1000
    turns = np.array([0, 90, 180, 270])
    clusters = wire_clusters(problem)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    # variable layout: x(n) y(n) z(n*4) s(4*pairs) t(2*clusters)
    ix, iy, iz = 0, n, 2*n
    isd = iz + 4*n
    it = isd + 4*len(pairs)
    nvar = it + 2*len(clusters)
    if proxy is not None:
        powered = set(np.flatnonzero(problem.power_w > 0))
        hot_pairs = [(p, i, j) for p, (i, j) in enumerate(pairs) if i in powered or j in powered]
        irho, itau = nvar, nvar + len(hot_pairs)
        ipk = itau + len(hot_pairs)
        nvar = ipk + 1
        if directions:
            iw = nvar
            nvar += directions*len(hot_pairs)
    rr, cc, vv, lo, hi = [], [], [], [], []

    def add(entries, low, high):
        for col, val in entries:
            rr.append(len(lo))
            cc.append(col)
            vv.append(val)
        lo.append(low)
        hi.append(high)

    size = problem.size_um/1000
    w = lambda i: [(iz + 4*i + r, (size[i, 1] if turns[r] % 180 else size[i, 0])) for r in range(4)]
    h = lambda i: [(iz + 4*i + r, (size[i, 0] if turns[r] % 180 else size[i, 1])) for r in range(4)]
    for i in range(n):
        add([(iz + 4*i + r, 1.0) for r in range(4)], 1, 1)
        add([(ix + i, 1.0)] + [(c, -v/2) for c, v in w(i)], 0, np.inf)              # x - w/2 >= 0
        add([(ix + i, 1.0)] + [(c, v/2) for c, v in w(i)], -np.inf, width)   # x + w/2 <= W
        add([(iy + i, 1.0)] + [(c, -v/2) for c, v in h(i)], 0, np.inf)
        add([(iy + i, 1.0)] + [(c, v/2) for c, v in h(i)], -np.inf, height)
    big = 2*max(width, height)
    for p, (i, j) in enumerate(pairs):
        s = isd + 4*p
        for q, (axis, first, second) in enumerate(((0, i, j), (0, j, i), (1, i, j), (1, j, i))):
            ext = w if axis == 0 else h
            base = ix if axis == 0 else iy
            # v_first + (ext_first + ext_second)/2 + gap <= v_second + big*(1 - s_q)
            add([(base + first, 1.0), (base + second, -1.0), (s + q, big)]
                + [(c, v/2) for c, v in ext(first)] + [(c, v/2) for c, v in ext(second)], -np.inf, big - gap)
        add([(s + q, 1.0) for q in range(4)], 1, np.inf)
    if proxy is not None:
        model, cap = proxy[:2]
        tau_of = {}
        for k, (p, i, j) in enumerate(hot_pairs):
            s = isd + 4*p
            if directions:
                far = 2*np.hypot(width, height)
                for d in range(directions):
                    ux, uy = np.cos(2*np.pi*d/directions), np.sin(2*np.pi*d/directions)
                    # rho <= u_d . (c_j - c_i) + far (1 - w_d)
                    add([(irho + k, 1.0), (ix + j, -ux), (ix + i, ux), (iy + j, -uy), (iy + i, uy),
                         (iw + directions*k + d, far)], -np.inf, far)
                add([(iw + directions*k + d, 1.0) for d in range(directions)], 1, 1)
            else:
                for q, (axis, first, second) in enumerate(((0, i, j), (0, j, i), (1, i, j), (1, j, i))):
                    base = ix if axis == 0 else iy
                    # rho <= v_second - v_first + big (1 - s_q)
                    add([(irho + k, 1.0), (base + second, -1.0), (base + first, 1.0), (s + q, big)], -np.inf, big)
            for a, b in zip(*model.pair_tangents(problem, i, j, gap_um)):
                add([(itau + k, 1.0), (irho + k, -b)], a, np.inf)              # tau >= a + b rho
            tau_of[(i, j)] = tau_of[(j, i)] = itau + k
        for i in range(n):
            limit = 0.0 if problem.limit_c is None else problem.limit_c[i]
            add([(ipk, 1.0)] + [(tau_of[(i, j)], -problem.power_w[j]) for j in sorted(powered) if j != i],
                problem.power_w[i]*model.self_k_w[i] - limit, np.inf)
    cost = np.zeros(nvar)
    for c, (i, j, k, oi, oj) in enumerate(clusters):
        ri, rj = rotate(np.tile(oi, (4, 1)), turns), rotate(np.tile(oj, (4, 1)), turns)
        for axis in (0, 1):
            t = it + 2*c + axis
            base = ix if axis == 0 else iy
            d = ([(base + i, 1.0), (base + j, -1.0)] + [(iz + 4*i + r, ri[r, axis]) for r in range(4)]
                 + [(iz + 4*j + r, -rj[r, axis]) for r in range(4)])
            add(d + [(t, -1.0)], -np.inf, 0)                    # d <= t
            add([(col, -v) for col, v in d] + [(t, -1.0)], -np.inf, 0)   # -d <= t
            cost[t] = k
    integrality = np.zeros(nvar)
    integrality[iz:it] = 1
    lower = np.r_[np.zeros(2*n), np.zeros(it - iz), np.zeros(nvar - it)]
    upper = np.r_[np.full(n, width), np.full(n, height), np.ones(it - iz), np.full(nvar - it, np.inf)]
    if proxy is not None:
        lower[irho:itau] = [(size[i].min() + size[j].min())/2 + gap for _, i, j in hot_pairs]
        upper[irho:itau] = np.hypot(width, height)
        if directions:
            integrality[iw:iw + directions*len(hot_pairs)] = 1
            upper[iw:iw + directions*len(hot_pairs)] = 1
        if problem.limit_c is not None:
            lower[ipk] = -np.inf          # a safe layout has negative overshoot; t is objective - ambient
        if proxy[1] is None:
            cost = cost*1e-6
            cost[ipk] = 1.0
        else:
            upper[ipk] = proxy[1] - AMBIENT_C
    if wire_mm is None and proxy is not None and len(proxy) > 2:
        wire_mm = proxy[2]
    if wire_mm is not None:                              # clustered wire <= budget (mm), cluster_length_mm units
        add([(it + 2*c + axis, k) for c, (_, _, k, _, _) in enumerate(clusters) for axis in (0, 1)], -np.inf, wire_mm)
        for cut in wire_cuts:
            entries, constant = pin_length_cut(problem, cut, ix, iy, iz)
            add(entries, -np.inf, wire_mm - constant)
    if thermal is not None:
        block = thermal[0].milp_block(add, nvar, ix, iy, iz, thermal[1])
        cost = np.r_[cost*block['length_weight'], block['cost']]
        integrality, lower, upper = (np.r_[a, block[k]] for a, k in ((integrality, 'integrality'), (lower, 'lb'),
                                                                      (upper, 'ub')))
        nvar += len(block['cost'])
    bounds = Bounds(lower, upper)
    matrix = sparse.csr_matrix((vv, (rr, cc)), shape=(len(lo), nvar))   # duplicates sum
    guess = None
    if start is not None:
        guess = np.full(nvar, np.nan)
        guess[ix:ix + n], guess[iy:iy + n] = start.centre_um[:, 0]/1000, start.centre_um[:, 1]/1000
        guess[iz:isd] = 0
        guess[iz + 4*np.arange(n) + (start.rotation_deg//90) % 4] = 1
        guess[isd:it] = 0
        for p, (i, j, axis, sign) in enumerate(centre_relations(problem, start, gap_um)):
            guess[isd + 4*p + 2*axis + (0 if sign > 0 else 1)] = 1
        if proxy is not None and directions:
            angles = 2*np.pi*np.arange(directions)/directions
            u = np.stack((np.cos(angles), np.sin(angles)), axis=1)
            guess[iw:iw + directions*len(hot_pairs)] = 0
            for k, (_, i, j) in enumerate(hot_pairs):
                guess[iw + directions*k + int(np.argmax(u @ (start.centre_um[j] - start.centre_um[i])))] = 1
    x = _solve_milp(cost, matrix, np.array(lo), np.array(hi), integrality, bounds, time_limit_s, threads, focus, guess)
    if x is None:
        return None
    rotation = turns[np.argmax(x[iz:isd].reshape(n, 4), axis=1)]
    layout = Layout(np.stack((x[ix:ix + n], x[iy:iy + n]), axis=1)*1000, rotation)
    return layout


def legalize_relations(problem, layout, gap_um):
    """Nearest legal layout (L1 displacement) that keeps the side relations read from the centres; or None.
    Unlike the length LP it does not pull dies back together, so a move that spreads hot dies survives."""
    n = problem.count
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
    width, height = (s/1000 for s in problem.carrier_um)
    x0 = layout.centre_um.T.ravel()/1000
    rows, cols, vals, rhs = [], [], [], []
    for r, (i, j, axis, sign) in enumerate(centre_relations(problem, layout, gap_um)):
        first, second = (i, j) if sign > 0 else (j, i)
        rows += [r, r]
        cols += [axis*n + first, axis*n + second]
        vals += [1.0, -1.0]
        rhs.append(-(size[first, axis] + size[second, axis])/2 - gap_um/1000)
    m = len(rhs)
    # |x - x0| <= u  ->  x - u <= x0, -x - u <= -x0
    for k in range(2*n):
        rows += [m + 2*k, m + 2*k, m + 2*k + 1, m + 2*k + 1]
        cols += [k, 2*n + k, k, 2*n + k]
        vals += [1.0, -1.0, -1.0, -1.0]
        rhs += [x0[k], -x0[k]]
    A = sparse.csr_matrix((vals, (rows, cols)), shape=(m + 4*n, 4*n))
    bounds = ([(size[k, 0]/2, width - size[k, 0]/2) for k in range(n)]
              + [(size[k, 1]/2, height - size[k, 1]/2) for k in range(n)] + [(0, None)]*(2*n))
    result = linprog(np.r_[np.zeros(2*n), np.ones(2*n)], A_ub=A, b_ub=rhs, bounds=bounds, method="highs")
    if result.status != 0:
        return None
    x = result.x
    centre = snap(problem, np.stack((x[:n], x[n:2*n]), axis=1)*1000, layout.rotation_deg, GRID_UM)
    legal = Layout(centre, layout.rotation_deg.copy())
    return legal if is_legal(problem, legal, gap_um) else None


def hotspot_move(problem, layout, die_peaks, rng, gap_um):
    """A discrete change aimed at the hottest die h, then `legalize_relations`: push away the die heating h
    most (power / squared distance), swap h with a low-power die far from it, or rotate h."""
    h = int(np.argmax(die_peaks))
    centre, rotation = layout.centre_um.copy(), layout.rotation_deg.copy()
    d = centre - centre[h]
    r2 = (d**2).sum(axis=1)/1e6 + 1.0                       # mm^2, +1 keeps it finite
    kind = rng.choice(("push", "swap", "rotate"), p=(.5, .3, .2))
    heat = problem.power_w/r2
    heat[h] = 0
    weight = r2/np.maximum(problem.power_w, 1e-6)
    weight[h] = 0
    if kind == "push" and heat.sum() > 0:
        j = int(rng.choice(problem.count, p=heat/heat.sum()))
        centre[j] += d[j]/np.sqrt(r2[j]*1e6)*rng.uniform(3, 8)*1000
    elif kind == "swap" and weight.sum() > 0:
        k = int(rng.choice(problem.count, p=weight/weight.sum()))
        centre[[h, k]] = centre[[k, h]]
    else:   # also when no other die heats h (or there is no other die): rotate h
        rotation[h] = (rotation[h] + rng.choice((90, 180, 270))) % 360
    return legalize_relations(problem, Layout(centre, rotation), gap_um)
