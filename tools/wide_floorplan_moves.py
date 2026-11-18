"""Constrained moves of eight die centres for a fixed wide interface pin assignment."""

from itertools import combinations
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize
from scipy.special import k0, k1, logsumexp, softmax

from case3_phy_geometry import (
    NEIGHBOURS,
    PROFILES,
    REACH_MM,
    RING,
    offset_table,
    sizes_mm,
)

SIGNS = np.array(((1, 1), (1, -1), (-1, 1), (-1, -1)))


def field_and_grad(xy, size, power, radii, weights, self_k):
    delta = xy[:, None, :] - xy[None, :, :]
    variance = (size**2).sum(axis=1) / 12
    distance = np.sqrt((delta**2).sum(axis=2) + variance[:, None] + variance[None, :])
    k = k0(distance[:, :, None] / radii) @ weights
    radial = -(k1(distance[:, :, None] / radii) @ (weights / radii)) / distance
    np.fill_diagonal(k, 0.0)
    np.fill_diagonal(radial, 0.0)
    values = (self_k + k @ power)[:4]
    mix = softmax(2 * values)
    flows = mix[:, None, None] * power[None, :, None] * radial[:4, :, None] * delta[:4]
    grad = -flows.sum(axis=0)
    grad[:4] += flows.sum(axis=1)
    return float(logsumexp(2 * values) / 2), grad.ravel()


class Assignment:
    def __init__(self, p, row, costs):
        self.size = sizes_mm(p, row["parity"])
        self.edges = []
        self.reach = []
        cf = row["profiles"]["wide"]
        turns = np.array(cf["rotation_deg"]) // 90
        for a, b in RING:
            sa = cf["sides"][a][NEIGHBOURS[a].index(b)]
            sb = cf["sides"][b][NEIGHBOURS[b].index(a)]
            values, prefix, support = offset_table(
                tuple(self.size[a]), tuple(self.size[b]), sa, sb, PROFILES["wide"]
            )
            self.edges.append((a, b, list(zip(values, prefix))))
            self.reach.append((a, b, support))
        for i in range(4):
            axes = costs.data[i, i + 4, turns[i], turns[i + 4]]
            self.edges.append((i, i + 4, [(v / 1000, pref / 1000) for v, pref in axes]))
        self.last = None

    def wire(self, x):
        if self.last is None or not np.array_equal(x, self.last):
            xy = x.reshape(8, 2)
            grad = np.zeros_like(xy)
            total = 0.0
            for a, b, axes in self.edges:
                for h, (v, prefix) in enumerate(axes):
                    d = xy[b, h] - xy[a, h]
                    k = v.searchsorted(d)
                    slope = 2 * k - len(v)
                    total += slope * d + prefix[-1] - 2 * prefix[k]
                    grad[b, h] += slope
                    grad[a, h] -= slope
            self.last = x.copy()
            self.cost = total / 1000
            self.grad = grad.ravel() / 1000
        return self.cost, self.grad

    def constraints(self, xy, variant):
        matrix = []
        rhs = []
        rng = np.random.default_rng(73)
        for a, b in combinations(range(8), 2):
            sep = (self.size[a] + self.size[b]) / 2
            delta = xy[b] - xy[a]
            slack = abs(delta) - sep
            axis = int(slack.argmax())
            if variant and slack.min() >= -1e-10 and rng.integers(2):
                axis = 1 - axis
            direction = 1 if delta[axis] >= 0 else -1
            v = np.zeros((8, 2))
            v[b, axis] = direction
            v[a, axis] = -direction
            matrix.append(v.ravel())
            rhs.append(sep[axis] + 0.0001)
        for a, b, support in self.reach:
            for s, h in zip(SIGNS, support):
                v = np.zeros((8, 2))
                v[b] = s
                v[a] = -s
                matrix.append(v.ravel())
                rhs.append(h - REACH_MM + 0.0021)
        return LinearConstraint(matrix, rhs, np.inf)


def move(row, cap, variant, state):
    p = state["p"]
    xy = np.array(row["centres_um"]) / 1000
    fixed = Assignment(p, row, state["costs"])
    assert abs(fixed.wire(xy.ravel())[0] - row["profiles"]["wide"]["wire_m"]) < 1e-7

    def objective(x):
        return field_and_grad(
            x.reshape(8, 2),
            fixed.size,
            p.power_w,
            state["radii"],
            state["weights"],
            state["self_k"],
        )

    wire = dict(
        type="ineq",
        fun=lambda x: cap - 0.015 - fixed.wire(x)[0],
        jac=lambda x: -fixed.wire(x)[1],
    )
    bounds = Bounds((fixed.size / 2).ravel(), (39 - fixed.size / 2).ravel())
    constraints = fixed.constraints(xy, variant)
    best = None

    def remember(x):
        nonlocal best
        if fixed.wire(x)[0] > cap - 0.0141 or np.any(
            constraints.A @ x < constraints.lb - 0.00005
        ):
            return
        val = objective(x)[0]
        if best is None or val < best[0]:
            best = (val, x.copy())

    r = minimize(
        objective,
        xy.ravel(),
        jac=True,
        method="SLSQP",
        bounds=bounds,
        constraints=[constraints, wire],
        callback=remember,
        options=dict(maxiter=95, ftol=2e-7),
    )
    remember(r.x)
    return best, r.success
