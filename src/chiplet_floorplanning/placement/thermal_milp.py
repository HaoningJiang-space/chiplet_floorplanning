"""Grid thermal kernels for the thermal-constrained relation MILP (plan: docs/thermal-milp-plan.md).

The carrier is cut into G x G cells. For every powered die size in each quarter-turn parity and every cell, the die
alone (1 W) is solved with the FV model at the cell centre (clamped to its feasible range); the kernel K[o][s][c, c']
is the hottest power-layer cell inside an observer of type o centred in cell c. With one-hot cell binaries g_j,c the
superposed temperature sum_j P_j K[o][s_j][c, c_j] is linear in g, so a hard cap needs no translation invariance and
keeps the package edges. Kernels ignore the better conduction of the other dies, which in the kernel screen made them
overestimate the FV peak; every MILP result is still confirmed by an exact FV solve.
"""
import numpy as np

from .problem import Layout, Problem
from .thermal import AMBIENT_C, PACKAGE_MM, solve, thermal_case_data

POINTS = np.linspace(-0.4, 0.4, 5)


def _lone_rise(args):
    """Power-layer rise (K) and cell edges (package mm) of one die alone, 1 W, unrotated at `centre_um`."""
    problem, size_um, centre_um, gap_um, resolution = args
    alone = Problem(problem.name, ('die',), np.array([size_um], float), np.ones(1), problem.carrier_um,
                    np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
    _, rise, edges = solve(thermal_case_data(alone, Layout(np.array([centre_um]), np.zeros(1, int)), gap_um, resolution))
    return rise, edges


class ThermalTable:
    def __init__(self, problem, gap_um, grid=6, resolution=64):
        """Cell geometry and the lone-die jobs; `solves` FV solves are made by `build`."""
        self.problem, self.grid = problem, grid
        width, height = problem.carrier_um
        self.x_edges, self.y_edges = np.linspace(0, width, grid + 1), np.linspace(0, height, grid + 1)
        self.powered = np.flatnonzero(problem.power_w > 0)
        self.key = {(j, t): tuple(problem.size_um[j][::-1] if t else problem.size_um[j])
                    for j in self.powered for t in (0, 1)}
        self.types = sorted(set(self.key.values()))
        cx, cy = (self.x_edges[:-1] + self.x_edges[1:])/2, (self.y_edges[:-1] + self.y_edges[1:])/2
        self.allowed, self.box, anchor = {}, {}, {}
        for o in self.types:
            w, h = o
            xlo = np.maximum(self.x_edges[:-1], w/2)
            xhi = np.minimum(self.x_edges[1:], width - w/2)
            ylo = np.maximum(self.y_edges[:-1], h/2)
            yhi = np.minimum(self.y_edges[1:], height - h/2)
            ok_x, ok_y = xlo <= xhi, ylo <= yhi
            # Cell c = row*grid + col (row along y).
            self.allowed[o] = (ok_y[:, None] & ok_x[None]).ravel()
            self.box[o] = tuple(np.broadcast_to(a, (grid, grid)).ravel()
                                for a in (xlo[None], xhi[None], ylo[:, None], yhi[:, None]))
            anchor[o] = np.stack(np.broadcast_arrays(np.clip(cx, w/2, width - w/2)[None],
                                                     np.clip(cy, h/2, height - h/2)[:, None]), -1).reshape(-1, 2)
        self.jobs = [(problem, o, anchor[o][c], gap_um, resolution)
                     for o in self.types for c in np.flatnonzero(self.allowed[o])]
        self.solves = len(self.jobs)
        offset = (PACKAGE_MM*1000 - np.array(problem.carrier_um))/2
        self.sample = {o: [(anchor[o][c][None] + np.stack(np.meshgrid(POINTS, POINTS), -1).reshape(-1, 2)*np.array(o)
                            + offset)/1000 for c in range(grid*grid)] for o in self.types}
        self.K = None

    def build(self, pool=None):
        """Solve the lone-die jobs and fill the kernel K[o][s] (G^2 x G^2, K/W)."""
        fields = list((pool.map if pool else map)(_lone_rise, self.jobs))
        grid, sample = self.grid, self.sample
        self.K = {o: {s: np.zeros((grid*grid, grid*grid)) for s in self.types} for o in self.types}
        k = 0
        for s in self.types:
            for c_src in np.flatnonzero(self.allowed[s]):
                rise, edges = fields[k]
                k += 1
                for o in self.types:
                    for c in np.flatnonzero(self.allowed[o]):
                        pts = sample[o][c]
                        col = np.clip(np.searchsorted(edges[0], pts[:, 0]) - 1, 0, rise.shape[1] - 1)
                        row = np.clip(np.searchsorted(edges[1], pts[:, 1]) - 1, 0, rise.shape[0] - 1)
                        self.K[o][s][c, c_src] = np.nanmax(rise[row, col])
        return self

    def cell(self, centre_um):
        centre_um = np.round(centre_um, 3)     # a solver's 19999.99999 um on the 20 mm edge is that edge
        col = np.clip(np.searchsorted(self.x_edges, centre_um[0], side='right') - 1, 0, self.grid - 1)
        row = np.clip(np.searchsorted(self.y_edges, centre_um[1], side='right') - 1, 0, self.grid - 1)
        return int(row*self.grid + col)

    def kernel_peak_c(self, layout):
        """Kernel estimate of the hottest powered die, degC, with each die in the cell holding its centre."""
        where = {j: (self.key[(j, int(layout.rotation_deg[j] % 180 != 0))], self.cell(layout.centre_um[j]))
                 for j in self.powered}
        return AMBIENT_C + max(sum(self.problem.power_w[j]*self.K[o][s][c, c_j] for j, (s, c_j) in where.items())
                               for o, c in where.values())

    def milp_block(self, add, base, ix, iy, iz, cap_c=None):
        """Variables and rows appended to the relation MILP after column `base` (x, y in mm; z one-hot turns).

        g (binary): powered die j with turn parity t has its centre in cell c, tied to the turn binaries and to the
        cell box; y (continuous, >= every g of its type there): observer type o occupies c. Temperature rows:
        sum P_j K g - big*(1 - y) <= cap - ambient, or, with cap_c None, <= tau (one more variable) to minimise.
        """
        G2 = self.grid**2
        order = list(self.key)
        g_at = {jt: base + k*G2 for k, jt in enumerate(order)}
        y_at = {o: base + len(order)*G2 + m*G2 for m, o in enumerate(self.types)}
        count = (len(order) + len(self.types))*G2 + (cap_c is None)
        tau = base + count - 1 if cap_c is None else None
        lb, ub, integrality = np.zeros(count), np.ones(count), np.zeros(count)
        integrality[:len(order)*G2] = 1
        width, height = (s/1000 for s in self.problem.carrier_um)
        for (j, t), g0 in g_at.items():
            o = self.key[(j, t)]
            ub[g0 - base:g0 - base + G2] = self.allowed[o]
            add([(g0 + c, 1.0) for c in range(G2)] + [(iz + 4*j + t, -1.0), (iz + 4*j + t + 2, -1.0)], 0, 0)
            xlo, xhi, ylo, yhi = (a/1000 for a in self.box[o])
            # Half-open cells, as in cell(): a centre on an inner edge belongs to the upper cell only.
            last_col, last_row = np.arange(G2) % self.grid == self.grid - 1, np.arange(G2) // self.grid == self.grid - 1
            xhi, yhi = np.where(last_col, xhi, xhi - 1e-4), np.where(last_row, yhi, yhi - 1e-4)
            for c in np.flatnonzero(self.allowed[o]):
                add([(ix + j, 1.0), (g0 + c, -width)], xlo[c] - width, np.inf)
                add([(ix + j, 1.0), (g0 + c, width)], -np.inf, xhi[c] + width)
                add([(iy + j, 1.0), (g0 + c, -height)], ylo[c] - height, np.inf)
                add([(iy + j, 1.0), (g0 + c, height)], -np.inf, yhi[c] + height)
                add([(y_at[o] + c, 1.0), (g0 + c, -1.0)], 0, np.inf)
        big = sum(self.problem.power_w[j]*max(self.K[o][self.key[(j, t)]].max() for o in self.types for t in (0, 1))
                  for j in self.powered)
        for o in self.types:
            for c in np.flatnonzero(self.allowed[o]):
                row = [(g0 + c2, self.problem.power_w[j]*self.K[o][self.key[(j, t)]][c, c2])
                       for (j, t), g0 in g_at.items() for c2 in np.flatnonzero(self.allowed[self.key[(j, t)]])]
                row = [(col, v) for col, v in row if v > 0] + [(y_at[o] + c, big)]
                if tau is None:
                    add(row, -np.inf, cap_c - AMBIENT_C + big)
                else:
                    add(row + [(tau, -1.0)], -np.inf, big)
        cost = np.zeros(count)
        if tau is not None:
            cost[-1], ub[-1] = 1.0, np.inf
        return dict(cost=cost, integrality=integrality, lb=lb, ub=ub, length_weight=1.0 if tau is None else 1e-6)
