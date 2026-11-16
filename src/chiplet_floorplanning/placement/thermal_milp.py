"""Grid thermal kernels for the thermal-constrained relation MILP (plan: docs/thermal-milp-plan.md).

Every powered die type (size in one quarter-turn parity) has cells that partition its feasible centre range; they
start as a G x G grid and `refine` splits the cells around a solution (adaptive grid). For each cell the die alone
(1 W) is solved with the FV model at the cell's centre; the kernel K[o][s][c, c'] is the hottest power-layer cell
inside an observer of type o centred in its cell c when a die of type s sits in cell c'. With one-hot cell binaries
g_j,c the superposed temperature sum_j P_j K[o][s_j][c, c_j] is linear in g, so a hard cap needs no translation
invariance and keeps the package edges. Kernels ignore the better conduction of the other dies, which in the kernel
screen made them overestimate the FV peak; every MILP result is still confirmed by an exact FV solve.
"""
import numpy as np

from .problem import Layout, Problem
from .thermal import AMBIENT_C, PACKAGE_MM, solve, thermal_case_data

POINTS = np.linspace(-0.4, 0.4, 5)
EDGE_UM = 0.1      # inner cell edges are half-open: a centre on an edge belongs to the cell above or right of it


def _lone_rise(args):
    """Power-layer rise (K) and cell edges (package mm) of one die alone, 1 W, unrotated at `centre_um`."""
    problem, size_um, centre_um, gap_um, resolution = args
    alone = Problem(problem.name, ('die',), np.array([size_um], float), np.ones(1), problem.carrier_um,
                    np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
    _, rise, edges = solve(thermal_case_data(alone, Layout(np.array([centre_um]), np.zeros(1, int)), gap_um, resolution))
    return rise, edges


class ThermalTable:
    def __init__(self, problem, gap_um, grid=6, resolution=64):
        """Initial G x G cells per die type; `solves` FV solves are pending until `build`."""
        self.problem, self.gap_um, self.resolution = problem, gap_um, resolution
        width, height = problem.carrier_um
        self.powered = np.flatnonzero(problem.power_w > 0)
        self.key = {(j, t): tuple(problem.size_um[j][::-1] if t else problem.size_um[j])
                    for j in self.powered for t in (0, 1)}
        self.types = sorted(set(self.key.values()))
        xe, ye = np.linspace(0, width, grid + 1), np.linspace(0, height, grid + 1)
        self.cells = {}
        for o in self.types:
            w, h = o
            boxes = [(max(x0, w/2), min(x1, width - w/2), max(y0, h/2), min(y1, height - h/2))
                     for y0, y1 in zip(ye[:-1], ye[1:]) for x0, x1 in zip(xe[:-1], xe[1:])]
            # A type that does not fit (e.g. a quarter turn of a die as long as the carrier) has no cells.
            self.cells[o] = np.array([b for b in boxes if b[0] <= b[1] and b[2] <= b[3]], float).reshape(-1, 4)
        self.fields = {}       # (type, anchor) -> lone-die FV field
        self.K = None

    def anchors(self, o):
        c = self.cells[o]
        return np.stack(((c[:, 0] + c[:, 1])/2, (c[:, 2] + c[:, 3])/2), axis=1)

    @property
    def solves(self):
        """Lone-die FV solves still needed for the current cells."""
        return sum((o, tuple(a)) not in self.fields for o in self.types for a in self.anchors(o))

    def build(self, pool=None):
        """Solve the pending lone-die fields and recompute every kernel K[o][s] (cells_o x cells_s, K/W)."""
        jobs = [(o, tuple(a)) for o in self.types for a in self.anchors(o) if (o, tuple(a)) not in self.fields]
        results = (pool.map if pool else map)(_lone_rise, [(self.problem, o, a, self.gap_um, self.resolution)
                                                          for o, a in jobs])
        self.fields.update(zip(jobs, results))
        offset = (PACKAGE_MM*1000 - np.array(self.problem.carrier_um))/2
        grid = np.stack(np.meshgrid(POINTS, POINTS), -1).reshape(-1, 2)
        self.K = {}
        for o in self.types:
            pts = [(a + grid*np.array(o) + offset)/1000 for a in self.anchors(o)]
            self.K[o] = {}
            for s in self.types:
                k = np.zeros((len(pts), len(self.cells[s])))
                for c_src, a in enumerate(self.anchors(s)):
                    rise, edges = self.fields[(s, tuple(a))]
                    for c, p in enumerate(pts):
                        col = np.clip(np.searchsorted(edges[0], p[:, 0]) - 1, 0, rise.shape[1] - 1)
                        row = np.clip(np.searchsorted(edges[1], p[:, 1]) - 1, 0, rise.shape[0] - 1)
                        k[c, c_src] = np.nanmax(rise[row, col])
                self.K[o][s] = k
        return self

    def cell(self, o, centre_um):
        """Index of the cell of type o holding the centre (half-open inner edges)."""
        x, y = np.round(centre_um, 3)     # a solver's 19999.99999 um on the 20 mm edge is that edge
        c = self.cells[o]
        inside = ((c[:, 0] <= x) & (c[:, 2] <= y) & ((x < c[:, 1]) | (c[:, 1] == c[:, 1].max()))
                  & ((y < c[:, 3]) | (c[:, 3] == c[:, 3].max())))
        if inside.any():
            return int(np.flatnonzero(inside)[0])
        gap = np.maximum(np.maximum(c[:, 0] - x, x - c[:, 1]), 0) + np.maximum(np.maximum(c[:, 2] - y, y - c[:, 3]), 0)
        return int(np.argmin(gap))

    def _where(self, layout):
        out = {}
        for j in self.powered:
            o = self.key[(j, int(layout.rotation_deg[j] % 180 != 0))]
            out[j] = (o, self.cell(o, layout.centre_um[j]))
        return out

    def kernel_peak_c(self, layout):
        """Kernel estimate of the hottest powered die, degC, with each die in the cell holding its centre."""
        where = self._where(layout)
        return AMBIENT_C + max(sum(self.problem.power_w[j]*self.K[o][s][c, c_j] for j, (s, c_j) in where.items())
                               for o, c in where.values())

    def refine(self, layout, split=2, apply=True):
        """Adaptive grid: split each powered die's cell and the cells touching it into split x split. Returns the
        number of lone-die solves the split cells need; with apply=False nothing changes (a budget check), else the
        cells are replaced and the kernels must be rebuilt by `build`."""
        cells = {}
        for o in self.types:
            chosen = set()
            for o2, c in self._where(layout).values():
                if o2 == o:
                    box, all_ = self.cells[o][c], self.cells[o]
                    near = ((all_[:, 0] <= box[1]) & (all_[:, 1] >= box[0])
                            & (all_[:, 2] <= box[3]) & (all_[:, 3] >= box[2]))
                    chosen |= set(np.flatnonzero(near))
            kept = [tuple(b) for i, b in enumerate(self.cells[o]) if i not in chosen]
            for i in sorted(chosen):
                x0, x1, y0, y1 = self.cells[o][i]
                xs, ys = np.linspace(x0, x1, split + 1), np.linspace(y0, y1, split + 1)
                kept += [(a, b, c, d) for c, d in zip(ys[:-1], ys[1:]) for a, b in zip(xs[:-1], xs[1:])]
            cells[o] = np.array(kept, float).reshape(-1, 4)
        pending = sum((o, ((c[0] + c[1])/2, (c[2] + c[3])/2)) not in self.fields for o in self.types for c in cells[o])
        if apply:
            self.cells, self.K = cells, None
        return pending

    def milp_block(self, add, base, ix, iy, iz, cap_c=None):
        """Variables and rows appended to the relation MILP after column `base` (x, y in mm; z one-hot turns).

        g (binary): powered die j with turn parity t has its centre in cell c of its type, tied to the turn binaries
        and to the cell box; y (continuous, >= every g of its type there): observer type o occupies c. Temperature
        rows: sum P_j K g - big*(1 - y) <= cap - ambient, or, with cap_c None, <= tau (one more variable) to minimise.
        """
        size = {o: len(self.cells[o]) for o in self.types}
        g_at, at = {}, base
        for jt in self.key:
            g_at[jt], at = at, at + size[self.key[jt]]
        n_g = at - base
        y_at = {}
        for o in self.types:
            y_at[o], at = at, at + size[o]
        tau = at if cap_c is None else None
        count = at - base + (cap_c is None)
        lb, ub, integrality = np.zeros(count), np.ones(count), np.zeros(count)
        integrality[:n_g] = 1
        width, height = (s/1000 for s in self.problem.carrier_um)
        for (j, t), g0 in g_at.items():
            o = self.key[(j, t)]
            add([(g0 + c, 1.0) for c in range(size[o])] + [(iz + 4*j + t, -1.0), (iz + 4*j + t + 2, -1.0)], 0, 0)
            xlo, xhi, ylo, yhi = (self.cells[o][:, k]/1000 for k in range(4))
            xhi = np.where(xhi < xhi.max(), xhi - EDGE_UM/1000, xhi)
            yhi = np.where(yhi < yhi.max(), yhi - EDGE_UM/1000, yhi)
            for c in range(size[o]):
                add([(ix + j, 1.0), (g0 + c, -width)], xlo[c] - width, np.inf)
                add([(ix + j, 1.0), (g0 + c, width)], -np.inf, xhi[c] + width)
                add([(iy + j, 1.0), (g0 + c, -height)], ylo[c] - height, np.inf)
                add([(iy + j, 1.0), (g0 + c, height)], -np.inf, yhi[c] + height)
                add([(y_at[o] + c, 1.0), (g0 + c, -1.0)], 0, np.inf)
        big = sum(self.problem.power_w[j]*max(self.K[o][self.key[(j, t)]].max(initial=0) for o in self.types for t in (0, 1))
                  for j in self.powered)
        for o in self.types:
            for c in range(size[o]):
                row = [(g0 + c2, self.problem.power_w[j]*self.K[o][self.key[(j, t)]][c, c2])
                       for (j, t), g0 in g_at.items() for c2 in range(size[self.key[(j, t)]])]
                row = [(col, v) for col, v in row if v > 0] + [(y_at[o] + c, big)]
                if tau is None:
                    add(row, -np.inf, cap_c - AMBIENT_C + big)
                else:
                    add(row + [(tau, -1.0)], -np.inf, big)
        cost = np.zeros(count)
        if tau is not None:
            cost[-1], ub[-1] = 1.0, np.inf
        return dict(cost=cost, integrality=integrality, lb=lb, ub=ub, length_weight=1.0 if tau is None else 1e-6)
