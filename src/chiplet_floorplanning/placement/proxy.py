"""One-dimensional thermal proxy: self-heating plus distance-decaying mutual heating (plan: docs/proxy-space-plan.md).

Heat spreads laterally in the spreader and sink and leaves through the top, so the rise one die causes at another
decays with centre distance r roughly as K0(r / lambda), lambda = sqrt(k t / h); the far-field form
g(r) = exp(c - r / lambda) / sqrt(r) is fitted to FV at nine distances. A die's peak is then approximated by
P_i s_i + sum_j P_j g(r_ij), with s_i the die's own rise per watt alone at the carrier centre. On front and random
layouts this ranked the FV peak with Spearman 0.979-0.996 (docs/physics-checks-plan.md) at about ten FV solves.
"""
from dataclasses import dataclass

import numpy as np

from .problem import Layout, Problem
from .thermal import AMBIENT_C, die_peaks_c, solve, thermal_case_data

R_MM = np.array([6., 8., 12., 16., 24., 32., 40., 50., 60.])
DEFAULT_H = 1/(.1*.06**2)
RESOLUTION = 64


def rise_c(problem, layout, gap_um=0.0, resolution=RESOLUTION):
    _, rise, edges = solve(thermal_case_data(problem, layout, gap_um, resolution))
    return die_peaks_c(problem, layout, rise, edges) - AMBIENT_C


def decay(h, resolution=RESOLUTION):
    """Mutual heating (K/W) of a 1 W, 5 x 5 mm source on a 1 x 1 mm unpowered die at the R_MM centre distances,
    in a 90 x 30 mm carrier with sink-top h."""
    problem = Problem('decay', ('src', 'obs'), np.array([[5000., 5000.], [1000., 1000.]]), np.array([1., 0.]),
                      (90000., 30000.), np.zeros((0, 2), int), np.zeros((0, 2, 2)), top_h_w_m2k=h)
    return np.array([rise_c(problem, Layout(np.array([[10000., 15000.], [10000. + r*1000, 15000.]]),
                                            np.zeros(2, int)), 0.0, resolution)[1] for r in R_MM])


def fit_lambda(r_mm, g):
    """(lambda mm, c) of ln g + 0.5 ln r = c - r / lambda over the points above 1% of the nearest one."""
    keep = g > 0.01*g[0]
    slope, c = np.polyfit(r_mm[keep], np.log(g[keep]) + 0.5*np.log(r_mm[keep]), 1)
    return -1/slope, c


def g_model(r_mm, lam, c):
    r = np.maximum(r_mm, 3.0)               # adjacent dies: keep the far-field form finite
    return np.exp(c - r/lam)/np.sqrt(r)


def self_heating(problem, gap_um, resolution=RESOLUTION):
    """Per die: its own peak rise (K/W) alone, 1 W, at the carrier centre; one solve per distinct size."""
    by_size = {}
    for k in range(problem.count):
        key = tuple(problem.size_um[k])
        if key not in by_size:
            alone = Problem(problem.name, ('die',), problem.size_um[k:k + 1], np.ones(1), problem.carrier_um,
                            np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
            by_size[key] = rise_c(alone, Layout(np.array(problem.carrier_um)[None]/2, np.zeros(1, int)), gap_um,
                                  resolution)[0]
    return np.array([by_size[tuple(s)] for s in problem.size_um]), len(by_size)


@dataclass(frozen=True)
class ThermalProxy:
    self_k_w: np.ndarray       # (n,) own rise per watt
    lam_mm: float
    c: float
    solves: int                # FV solves spent on the calibration

    @classmethod
    def calibrate(cls, problem, gap_um, resolution=RESOLUTION):
        lam, c = fit_lambda(R_MM, decay(problem.top_h_w_m2k or DEFAULT_H, resolution))
        s, sizes = self_heating(problem, gap_um, resolution)
        return cls(s, float(lam), float(c), len(R_MM) + sizes)

    def g(self, r_mm):
        return g_model(np.asarray(r_mm, float), self.lam_mm, self.c)

    def die_rise_c(self, problem, layout):
        """(n,) proxy rise of every die: P_i s_i + sum_j P_j g(r_ij), centre distances."""
        d = np.linalg.norm(layout.centre_um[:, None] - layout.centre_um[None], axis=2)/1000
        mutual = self.g(d)*problem.power_w[None]
        np.fill_diagonal(mutual, 0.0)
        return problem.power_w*self.self_k_w + mutual.sum(axis=1)

    def peak_c(self, problem, layout):
        """Absolute peak of the Euclidean proxy, even when the search uses per-die limits."""
        return AMBIENT_C + float(self.die_rise_c(problem, layout).max())

    def objective(self, problem, rise):
        """Peak in degC, or worst per-die overshoot in K when absolute limits are supplied."""
        value = AMBIENT_C + rise
        if problem.limit_c is not None:
            value = value - problem.limit_c
        return float(value.max())

    def value(self, problem, layout):
        """Euclidean proxy in the search objective's units; not the MILP envelope."""
        return self.objective(problem, self.die_rise_c(problem, layout))

    def pair_tangents(self, problem, i, j, gap_um):
        """Shared pair coefficients for the MILP and its fixed-layout evaluation."""
        low = (problem.size_um[i].min() + problem.size_um[j].min())/2000 + gap_um/1000
        return self.tangents(low, np.hypot(*problem.carrier_um)/1000)

    def envelope_value(self, problem, layout, gap_um):
        """Minimum MILP envelope at a fixed legal layout, in the search objective's units.

        Each pair chooses its largest admissible separating-axis distance. Since every pair contribution has a
        nonnegative power coefficient and the tangent envelope decreases, those independent choices attain the
        smallest feasible envelope. This is not a bound on FV temperature.
        """
        size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
        rise = problem.power_w*self.self_k_w
        for i in range(problem.count):
            for j in range(i + 1, problem.count):
                if problem.power_w[i] == problem.power_w[j] == 0:
                    continue
                delta = np.abs(layout.centre_um[i] - layout.centre_um[j])
                separated = delta >= (size[i] + size[j])/2 + gap_um - 1e-4  # solver roundoff, um
                if not separated.any():
                    raise ValueError('proxy envelope requires separated chiplets')
                rho = delta[separated].max()/1000
                a, b = self.pair_tangents(problem, i, j, gap_um)
                tau = max(0.0, float((a + b*rho).max()))
                rise[i] += problem.power_w[j]*tau
                rise[j] += problem.power_w[i]*tau
        return self.objective(problem, rise)

    def polygon_value(self, problem, layout, gap_um, directions):
        """Minimum of the K-direction MILP representation at a fixed layout, in the search objective's units:
        rho_ij = max_k u_k . (c_j - c_i) (a lower bound of the centre distance, within cos(pi/K) of it) through the
        tangent envelope of g. Not a bound on FV temperature (docs/polygon-distance-plan.md)."""
        angles = 2*np.pi*np.arange(directions)/directions
        u = np.stack((np.cos(angles), np.sin(angles)), axis=1)
        rise = problem.power_w*self.self_k_w
        for i in range(problem.count):
            for j in range(i + 1, problem.count):
                if problem.power_w[i] == problem.power_w[j] == 0:
                    continue
                rho = float((u @ (layout.centre_um[j] - layout.centre_um[i])).max())/1000
                a, b = self.pair_tangents(problem, i, j, gap_um)
                tau = max(0.0, float((a + b*rho).max()))
                rise[i] += problem.power_w[j]*tau
                rise[j] += problem.power_w[i]*tau
        return self.objective(problem, rise)

    def tangents(self, low_mm, high_mm, count=12):
        """(intercept, slope) of tangents to g at count points spaced geometrically on [low, high]; g is convex and
        decreasing there (low >= 3 mm), so their maximum is an outer approximation of its epigraph."""
        points = np.geomspace(max(low_mm, 3.0), max(high_mm, low_mm + 1e-6, 3.0 + 1e-6), count)
        value = self.g(points)
        slope = value*(-1/self.lam_mm - 0.5/points)
        return value - slope*points, slope
