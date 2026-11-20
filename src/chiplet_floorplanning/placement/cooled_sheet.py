"""Steady response of a thin copper sheet under a localized cooled contact."""

import numpy as np
from scipy.sparse import diags, kronsum
from scipy.sparse.linalg import splu

from .geometry import boxes


VERTICAL_MM2_K_W = 5.75
LATERAL_W_K = 0.4


def footprint(edges, lower, upper):
    lengths = np.maximum(0., np.minimum(edges[1:, None], upper) - np.maximum(edges[:-1, None], lower))
    return np.outer(lengths[:, 1], lengths[:, 0])


class CooledSheet:
    """Unit-square mm copper cells. One fixed conductance matrix per cooled contact."""

    def __init__(self, problem, centre):
        side = max(100., max(problem.carrier_um)/1000 + 20.)
        n = int(side)
        assert n == side
        self.edges = np.arange(n+1) + (200-side)/2
        self.carrier_offset = (200 - np.asarray(problem.carrier_um)/1000)/2
        line = diags((-np.ones(n-1), [1., *([2.]*(n-2)), 1.], -np.ones(n-1)), (-1, 0, 1))
        contact_area = footprint(self.edges, centre-15, centre+15)
        assert abs(contact_area.sum()-900) < 1e-8
        # k*t = 0.4 W/K laterally. Through-plane resistance uses mm² K/W.
        self.sink = contact_area.ravel() / (.5/.4 + 6.9/.4 + 1/.02)
        self.factor = splu((LATERAL_W_K * kronsum(line, line) + diags(self.sink)).tocsc())
        self.problem = problem

    def power_map(self, layout):
        xy = boxes(self.problem, layout) / 1000 + np.tile(self.carrier_offset, 2)
        watts = np.zeros((len(self.edges)-1,)*2)
        for box, power in zip(xy, self.problem.power_w):
            lower, upper = box[:2], box[2:]
            watts += footprint(self.edges, lower, upper) * (power / np.prod(upper - lower))
        assert abs(watts.sum() - self.problem.power_w.sum()) < 1e-8
        return watts

    def temperatures(self, watts):
        rise = self.factor.solve(watts.ravel())
        assert abs(self.sink @ rise - watts.sum()) < 1e-7
        # Cell area is 1 mm²; fractional coverage is area-averaged consistently with the sources.
        return (rise + VERTICAL_MM2_K_W * watts.ravel()).reshape(watts.shape)

    def peak(self, layout):
        return float(self.temperatures(self.power_map(layout)).max())
