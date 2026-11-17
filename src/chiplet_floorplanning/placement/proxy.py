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
        return AMBIENT_C + float(self.die_rise_c(problem, layout).max())

    def tangents(self, low_mm, high_mm, count=12):
        """(intercept, slope) of tangents to g at count points spaced geometrically on [low, high]; g is convex and
        decreasing there (low >= 3 mm), so their maximum is an outer approximation of its epigraph."""
        points = np.geomspace(max(low_mm, 3.0), max(high_mm, low_mm + 1e-6, 3.0 + 1e-6), count)
        value = self.g(points)
        slope = value*(-1/self.lam_mm - 0.5/points)
        return value - slope*points, slope
