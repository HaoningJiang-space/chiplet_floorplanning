"""Pick a direct chiplet translation or exchange by heat spreading under a hard connection budget."""

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .geometry import boxes, is_legal, pin_points_um
from .problem import Layout
from .search import rotated_size


def rectangle_resistance(offset_um, size_um):
    """Surface-centre response (K/W) of a uniform rectangular patch on a copper half-space."""
    x, y = np.moveaxis(np.asarray(offset_um) / 1000, -1, 0)
    w, h = np.moveaxis(np.asarray(size_um) / 1000, -1, 0)

    def primitive(x, y):
        # Continuous values on both axes, including the integrable source singularity.
        return (x * np.arcsinh(y / np.where(x == 0, 1., abs(x)))
                + y * np.arcsinh(x / np.where(y == 0, 1., abs(y))))

    lo_x, hi_x = x - w / 2, x + w / 2
    lo_y, hi_y = y - h / 2, y + h / 2
    integral = (primitive(hi_x, hi_y) - primitive(lo_x, hi_y)
                - primitive(hi_x, lo_y) + primitive(lo_x, lo_y))
    return integral / (2 * np.pi * 0.4 * w * h)  # k = 0.4 W/(mm K)


class SpreadingField:
    def __init__(self, problem, layout):
        self.sizes = rotated_size(problem, layout.rotation_deg)
        self.power = problem.power_w
        self.centres = layout.centre_um
        # Half of 0.15 mm silicon (100 W/mK), then 0.02 mm TIM (4 W/mK).
        self.vertical = (0.075 / 0.1 + 0.02 / 0.004) * self.power / (self.sizes.prod(axis=1) / 1e6)
        self.contributions = self.patches(self.centres, self.centres)
        self.initial = self.contributions.sum(axis=1) + self.vertical

    def patches(self, observers, sources):
        return rectangle_resistance(observers[..., None, :] - sources, self.sizes) * self.power

    def rises(self, centres):
        return self.patches(centres, centres).sum(axis=1) + self.vertical

    def translation_peaks(self, chip, destinations):
        # Every fixed observer loses the old contribution and receives the new one.
        source = rectangle_resistance(self.centres - destinations[:, None], self.sizes[chip])
        rises = self.initial - self.contributions[:, chip] + source * self.power[chip]
        # The moving observer travels with its own source. Its self-heating is unchanged.
        at_new = self.patches(destinations, self.centres)
        at_new[:, chip] = self.contributions[chip, chip]
        rises[:, chip] = at_new.sum(axis=1) + self.vertical[chip]
        return rises.max(axis=1)


class ConnectionCost:
    """Exact change to the chosen rigid-pin or demand-weighted Manhattan cost."""

    def __init__(self, problem, layout, demand=None):
        if demand is None:
            self.chips = problem.pin_chip
            pts = pin_points_um(problem, layout)
            self.vectors = pts[:, 0] - pts[:, 1]
            self.weights = np.ones(len(pts)) / 1e6  # sum in m
        else:
            i, j = np.nonzero(demand)
            self.chips = np.column_stack((i, j))
            self.vectors = layout.centre_um[i] - layout.centre_um[j]
            self.weights = demand[i, j] / (demand.sum() * 1000)  # weighted average in mm
        self.initial = float(abs(self.vectors).sum(axis=1) @ self.weights)

    def translations(self, chip, offsets):
        plus, minus = self.chips[:, 0] == chip, self.chips[:, 1] == chip
        incident = plus ^ minus
        vectors = self.vectors[incident] * np.where(plus[incident], 1, -1)[:, None]
        weights = self.weights[incident]
        costs = np.full(len(offsets), self.initial)
        for axis in (0, 1):
            shifts, inverse = np.unique(offsets[:, axis], return_inverse=True)
            change = abs(vectors[:, axis] + shifts[:, None]) - abs(vectors[:, axis])
            costs += (change @ weights)[inverse]
        return costs

    def shifted(self, delta):
        vectors = self.vectors + delta[self.chips[:, 0]] - delta[self.chips[:, 1]]
        return float(abs(vectors).sum(axis=1) @ self.weights)


@dataclass(frozen=True)
class Landing:
    chips: tuple
    destinations_um: tuple
    cost: float
    rise_k: float

    def apply(self, layout):
        xy = layout.centre_um.copy()
        for chip, target in zip(self.chips, self.destinations_um):
            xy[chip] = target
        return Layout(xy, layout.rotation_deg.copy())


def legal_destinations(problem, layout, chip, gap_um, grid_um):
    """Every feasible final centre on the translation lattice, including disconnected pockets."""
    p = layout.centre_um[chip]
    half = rotated_size(problem, layout.rotation_deg)[chip] / 2
    lower = np.ceil((half - p) / grid_um).astype(int)
    upper = np.floor((np.array(problem.carrier_um) - half - p) / grid_um).astype(int)
    x, y = np.meshgrid(np.arange(lower[0], upper[0] + 1), np.arange(lower[1], upper[1] + 1))
    xy = p + grid_um * np.column_stack((x.ravel(), y.ravel()))
    valid = (xy != p).any(axis=1)
    for other, (x0, y0, x1, y1) in enumerate(boxes(problem, layout)):
        if other != chip:
            valid &= ((xy[:, 0] + half[0] + gap_um <= x0) | (xy[:, 0] - half[0] >= x1 + gap_um)
                      | (xy[:, 1] + half[1] + gap_um <= y0) | (xy[:, 1] - half[1] >= y1 + gap_um))
    return xy[valid]


def landing_bank(problem, footprint, layout, connections, *, gap_um=100, grid_um=1000):
    """Score the unchanged design and every legal single translation or two-centre exchange."""
    field = SpreadingField(problem, layout)
    points = [Landing((), (), connections.initial, float(field.initial.max()))]
    for k in range(problem.count):
        xy = legal_destinations(footprint, layout, k, gap_um, grid_um)
        if len(xy):
            costs = connections.translations(k, xy - layout.centre_um[k])
            peaks = field.translation_peaks(k, xy)
            points.extend(Landing((k,), (tuple(pos),), float(cost), float(peak))
                          for pos, cost, peak in zip(xy, costs, peaks))
    for i, j in combinations(range(problem.count), 2):
        xy = layout.centre_um.copy()
        xy[[i, j]] = xy[[j, i]]
        if is_legal(footprint, Layout(xy, layout.rotation_deg), gap_um):
            points.append(Landing((i, j), (tuple(xy[i]), tuple(xy[j])), connections.shifted(xy - layout.centre_um),
                                  float(field.rises(xy).max())))
    return points, field


def select_landing(points, cap, *, movable=None):
    """One deterministic decision. A thermally tied move does not displace the starting layout."""
    start = points[0]
    if start.cost > cap + 1e-9:
        raise ValueError("starting layout exceeds the supplied cap")
    eligible = (p for p in points if p.cost <= cap + 1e-9 and (movable is None or movable in p.chips))
    best = min(eligible, default=start, key=lambda p: (p.rise_k, p.cost))
    return best if best.rise_k < start.rise_k - 1e-9 else start
